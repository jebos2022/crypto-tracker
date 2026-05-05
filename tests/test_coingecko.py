import os
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from core import coingecko


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self.payload = payload if payload is not None else {}

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None, headers=None):
        self.requests.append({"url": url, "params": params, "headers": headers})
        if not self.responses:
            raise AssertionError("Unexpected HTTP request")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class CoinGeckoClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "prices.db"
        self.original_get_connection = coingecko.get_connection
        self.original_env = {
            "COINGECKO_API_KEY": os.environ.get("COINGECKO_API_KEY"),
            "COINGECKO_DAILY_CALL_BUDGET": os.environ.get("COINGECKO_DAILY_CALL_BUDGET"),
        }
        coingecko.get_connection = self._conn
        coingecko._last_call_at = None
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE price_fetch_log (
                    date TEXT NOT NULL,
                    source TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (date, source)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE price_cache (
                    coingecko_id TEXT NOT NULL,
                    date TEXT NOT NULL,
                    eur TEXT NOT NULL,
                    source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (coingecko_id, date)
                )
                """
            )

    def tearDown(self) -> None:
        coingecko.get_connection = self.original_get_connection
        coingecko._last_call_at = None
        for key, value in self.original_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_headers_use_api_key_when_present(self) -> None:
        os.environ["COINGECKO_API_KEY"] = "demo-key"

        self.assertEqual(coingecko.headers(), {"x-cg-demo-api-key": "demo-key"})

    def test_calls_today_reads_price_fetch_log(self) -> None:
        today = coingecko.date.today().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO price_fetch_log (date, source, count) VALUES (?, ?, ?)",
                (today, coingecko.SOURCE, 7),
            )

        self.assertEqual(coingecko.calls_today(), 7)

    def test_request_logs_each_successful_http_call(self) -> None:
        fake = FakeClient([FakeResponse(200, {"ok": True})])

        with patch.object(coingecko.httpx, "Client", return_value=fake):
            payload = coingecko.request_json("/simple/price", {"ids": "ethereum"})

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(coingecko.calls_today(), 1)
        self.assertEqual(fake.requests[0]["url"], f"{coingecko.COINGECKO_BASE}/simple/price")
        self.assertEqual(fake.requests[0]["params"], {"ids": "ethereum"})

    def test_budget_guard_skips_http_when_exhausted(self) -> None:
        os.environ["COINGECKO_DAILY_CALL_BUDGET"] = "1"
        today = coingecko.date.today().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO price_fetch_log (date, source, count) VALUES (?, ?, ?)",
                (today, coingecko.SOURCE, 1),
            )
        fake = FakeClient([])

        with patch.object(coingecko.httpx, "Client", return_value=fake):
            payload = coingecko.request_json("/ping")

        self.assertIsNone(payload)
        self.assertEqual(fake.requests, [])
        self.assertEqual(coingecko.calls_today(), 1)

    def test_transport_errors_are_retried_and_logged(self) -> None:
        fake = FakeClient([
            coingecko.httpx.ConnectError("network down"),
            FakeResponse(200, {"ok": True}),
        ])

        with (
            patch.object(coingecko.httpx, "Client", return_value=fake),
            patch.object(coingecko.time, "sleep"),
        ):
            payload = coingecko.request_json("/ping")

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(coingecko.calls_today(), 2)

    def test_temporary_errors_retry_with_backoff_and_log_each_attempt(self) -> None:
        fake = FakeClient([
            FakeResponse(429, {"error": "rate"}),
            FakeResponse(503, {"error": "busy"}),
            FakeResponse(200, {"ok": True}),
        ])
        sleeps = []

        with (
            patch.object(coingecko.httpx, "Client", return_value=fake),
            patch.object(coingecko.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)),
        ):
            payload = coingecko.request_json("/ping")

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(coingecko.calls_today(), 3)
        self.assertIn(1.0, sleeps)
        self.assertIn(2.0, sleeps)

    def test_minimum_interval_between_sequential_calls(self) -> None:
        coingecko._last_call_at = 100.0
        fake = FakeClient([FakeResponse(200, {"ok": True})])
        sleeps = []

        with (
            patch.object(coingecko.httpx, "Client", return_value=fake),
            patch.object(coingecko.time, "monotonic", side_effect=[101.0, 101.0]),
            patch.object(coingecko.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)),
        ):
            coingecko.request_json("/ping")

        self.assertIn(1.5, sleeps)

    def test_fetch_price_is_cache_first(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO price_cache (coingecko_id, date, eur, source, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("ethereum", "2026-01-01", "1234.56", coingecko.SOURCE, "2026-01-02T00:00:00Z"),
            )

        with patch.object(coingecko, "request_json") as request:
            price = coingecko.fetch_price("ethereum", date(2026, 1, 1))

        self.assertEqual(price, Decimal("1234.56"))
        request.assert_not_called()

    def test_fetch_price_second_call_uses_cache(self) -> None:
        payload = {"prices": [[_ms(2026, 1, 1, 23), "2000.25"]]}

        with patch.object(coingecko, "request_json", return_value=payload) as request:
            first = coingecko.fetch_price("ethereum", date(2026, 1, 1))
            second = coingecko.fetch_price("ethereum", date(2026, 1, 1))

        self.assertEqual(first, Decimal("2000.25"))
        self.assertEqual(second, Decimal("2000.25"))
        self.assertEqual(request.call_count, 1)

    def test_fetch_price_range_uses_market_chart_and_writes_daily_rows(self) -> None:
        payload = {
            "prices": [
                [_ms(2026, 1, 1, 9), "10.1"],
                [_ms(2026, 1, 1, 23), "10.2"],
                [_ms(2026, 1, 2, 23), "11.3"],
                [_ms(2026, 1, 3, 0), "12.0"],
            ]
        }

        with patch.object(coingecko, "request_json", return_value=payload) as request:
            prices = coingecko.fetch_price_range("usd-coin", date(2026, 1, 1), date(2026, 1, 2))

        self.assertEqual(prices, {date(2026, 1, 1): Decimal("10.2"), date(2026, 1, 2): Decimal("11.3")})
        request.assert_called_once()
        path, params = request.call_args.args
        self.assertEqual(path, "/coins/usd-coin/market_chart/range")
        self.assertEqual(params["vs_currency"], "eur")
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT date, eur FROM price_cache WHERE coingecko_id = ? ORDER BY date",
                ("usd-coin",),
            ).fetchall()
        self.assertEqual([(row["date"], row["eur"]) for row in rows], [("2026-01-01", "10.2"), ("2026-01-02", "11.3")])

    def test_fetch_price_range_does_not_fallback_to_wrong_date(self) -> None:
        payload = {"prices": [[_ms(2026, 1, 2, 23), "11.3"]]}

        with patch.object(coingecko, "request_json", return_value=payload):
            prices = coingecko.fetch_price_range("usd-coin", date(2026, 1, 1), date(2026, 1, 1))

        self.assertEqual(prices, {})

    def test_old_current_price_is_not_used_as_historical_close(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO price_cache (coingecko_id, date, eur, source, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("ethereum", "2000-01-01", "1000", coingecko.PRICE_SOURCE_CURRENT, "2000-01-01T12:00:00Z"),
            )
        payload = {"prices": [[_ms(2000, 1, 1, 23), "1100"]]}

        with patch.object(coingecko, "request_json", return_value=payload) as request:
            price = coingecko.fetch_price("ethereum", date(2000, 1, 1))

        self.assertEqual(price, Decimal("1100"))
        request.assert_called_once()

    def test_fetch_current_prices_uses_simple_price_and_caches_today(self) -> None:
        payload = {"ethereum": {"eur": "2100.5"}, "usd-coin": {"eur": "0.93"}}

        with patch.object(coingecko, "request_json", return_value=payload) as request:
            prices = coingecko.fetch_current_prices(["usd-coin", "ethereum", "ethereum"])

        self.assertEqual(prices, {"ethereum": Decimal("2100.5"), "usd-coin": Decimal("0.93")})
        request.assert_called_once_with(
            "/simple/price",
            {"ids": "ethereum,usd-coin", "vs_currencies": "eur"},
        )
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT coingecko_id, eur FROM price_cache WHERE date = ? ORDER BY coingecko_id",
                (date.today().isoformat(),),
            ).fetchall()
        self.assertEqual([(row["coingecko_id"], row["eur"]) for row in rows], [("ethereum", "2100.5"), ("usd-coin", "0.93")])

    def test_fetch_current_prices_returns_cached_today_without_http(self) -> None:
        with self._conn() as conn:
            conn.executemany(
                """
                INSERT INTO price_cache (coingecko_id, date, eur, source, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    ("ethereum", date.today().isoformat(), "1999.5", coingecko.PRICE_SOURCE_CURRENT, "2026-01-02T00:00:00Z"),
                    ("usd-coin", date.today().isoformat(), "0.99", coingecko.PRICE_SOURCE_CURRENT, "2026-01-02T00:00:00Z"),
                ],
            )

        with patch.object(coingecko, "request_json") as request:
            prices = coingecko.fetch_current_prices(["ethereum", "usd-coin"])

        self.assertEqual(prices, {"ethereum": Decimal("1999.5"), "usd-coin": Decimal("0.99")})
        request.assert_not_called()

    def test_fetch_current_prices_fetches_only_missing_ids(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO price_cache (coingecko_id, date, eur, source, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("ethereum", date.today().isoformat(), "1999.5", coingecko.PRICE_SOURCE_CURRENT, "2026-01-02T00:00:00Z"),
            )
        payload = {"usd-coin": {"eur": "0.93"}}

        with patch.object(coingecko, "request_json", return_value=payload) as request:
            prices = coingecko.fetch_current_prices(["ethereum", "usd-coin"])

        self.assertEqual(prices, {"ethereum": Decimal("1999.5"), "usd-coin": Decimal("0.93")})
        request.assert_called_once_with(
            "/simple/price",
            {"ids": "usd-coin", "vs_currencies": "eur"},
        )

    def test_fetch_current_prices_returns_cached_today_when_budget_exhausted(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO price_cache (coingecko_id, date, eur, source, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                ("ethereum", date.today().isoformat(), "1999.5", coingecko.SOURCE, "2026-01-02T00:00:00Z"),
            )

        with patch.object(coingecko, "request_json", return_value=None):
            prices = coingecko.fetch_current_prices(["ethereum", "usd-coin"])

        self.assertEqual(prices, {"ethereum": Decimal("1999.5")})

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn


def _ms(year: int, month: int, day: int, hour: int) -> int:
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


if __name__ == "__main__":
    unittest.main()
