import os
import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from decimal import Decimal, InvalidOperation

import httpx

from core.db import get_connection


COINGECKO_BASE = "https://api.coingecko.com/api/v3"
SOURCE = "coingecko"
PRICE_SOURCE_MARKET_CHART = "coingecko_market_chart"
PRICE_SOURCE_CURRENT = "coingecko_current"
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 5
INITIAL_BACKOFF = 1.0
MIN_CALL_INTERVAL = 2.5
TEMPORARY_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_DAILY_CALL_BUDGET = 300

_last_call_at: float | None = None


class CoinGeckoError(Exception):
    """Raised when CoinGecko returns an unrecoverable or exhausted error."""


class CoinGeckoBudgetExceeded(CoinGeckoError):
    """Raised by strict callers when the daily CoinGecko budget is exhausted."""


def headers() -> dict[str, str]:
    key = os.getenv("COINGECKO_API_KEY", "").strip()
    return {"x-cg-demo-api-key": key} if key else {}


def daily_call_budget() -> int:
    raw = os.getenv("COINGECKO_DAILY_CALL_BUDGET", "").strip()
    if not raw:
        return DEFAULT_DAILY_CALL_BUDGET
    try:
        budget = int(raw)
    except ValueError:
        return DEFAULT_DAILY_CALL_BUDGET
    return max(0, budget)


def calls_today(source: str = SOURCE, day: str | None = None) -> int:
    log_date = day or date.today().isoformat()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT count FROM price_fetch_log WHERE date = ? AND source = ?",
            (log_date, source),
        ).fetchone()
        return int(row["count"]) if row else 0
    finally:
        conn.close()


def budget_remaining(source: str = SOURCE, day: str | None = None) -> int:
    return max(0, daily_call_budget() - calls_today(source, day))


def request_json(
    path: str,
    params: dict | None = None,
    *,
    source: str = SOURCE,
    cache_only_on_budget: bool = True,
):
    """
    Make a budget-guarded CoinGecko GET request.

    Price-specific cache lookup lives in 3.4; in 3.3 this returns None when
    the daily budget is exhausted so higher layers can stay cache-only.
    """
    url = _url_for(path)
    request_params = params or {}
    last_error: Exception | None = None

    if calls_today(source) >= daily_call_budget():
        if cache_only_on_budget:
            return None
        raise CoinGeckoBudgetExceeded("CoinGecko daily call budget exhausted")

    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        for attempt in range(MAX_RETRIES + 1):
            if calls_today(source) >= daily_call_budget():
                if cache_only_on_budget:
                    return None
                raise CoinGeckoBudgetExceeded("CoinGecko daily call budget exhausted")

            _wait_for_call_slot()
            try:
                response = client.get(url, params=request_params, headers=headers())
            except httpx.TransportError as exc:
                _record_call(source)
                _remember_call_time()
                last_error = exc
                if attempt >= MAX_RETRIES:
                    break
                _sleep_backoff(attempt)
                continue
            _record_call(source)
            _remember_call_time()

            if response.status_code in TEMPORARY_STATUS_CODES:
                last_error = CoinGeckoError(f"Temporary CoinGecko HTTP {response.status_code}")
                if attempt >= MAX_RETRIES:
                    break
                _sleep_backoff(attempt)
                continue

            if response.status_code >= 400:
                raise CoinGeckoError(f"CoinGecko HTTP {response.status_code}")

            try:
                return response.json()
            except ValueError as exc:
                raise CoinGeckoError("CoinGecko returned invalid JSON") from exc

    raise CoinGeckoError("CoinGecko request failed after retries") from last_error


def fetch_price(coingecko_id: str, price_date: date | datetime | str) -> Decimal | None:
    target_date = _as_date(price_date)
    cached = _cached_price(coingecko_id, target_date)
    if cached is not None:
        return cached
    return fetch_price_range(coingecko_id, target_date, target_date).get(target_date)


def fetch_price_range(
    coingecko_id: str,
    start: date | datetime | str,
    end: date | datetime | str,
) -> dict[date, Decimal]:
    start_date = _as_date(start)
    end_date = _as_date(end)
    if start_date > end_date:
        raise ValueError("start must be before or equal to end")

    requested_dates = _date_span(start_date, end_date)
    cached = {
        day: price
        for day in requested_dates
        for price in (_cached_price(coingecko_id, day),)
        if price is not None
    }
    if len(cached) == len(requested_dates):
        return cached

    payload = request_json(
        f"/coins/{coingecko_id}/market_chart/range",
        {
            "vs_currency": "eur",
            "from": _unix_start(start_date),
            "to": _unix_start(end_date + timedelta(days=1)),
        },
    )
    if payload is None:
        return cached

    fetched = _daily_prices_from_market_chart(payload, start_date, end_date)
    for day, price in fetched.items():
        _upsert_price(coingecko_id, day, price)

    return {day: price for day in requested_dates for price in (fetched.get(day, cached.get(day)),) if price is not None}


def fetch_current_prices(coingecko_ids: list[str]) -> dict[str, Decimal]:
    ids = sorted({coingecko_id.strip() for coingecko_id in coingecko_ids if coingecko_id.strip()})
    if not ids:
        return {}

    today = date.today()
    cached = {
        coingecko_id: price
        for coingecko_id in ids
        for price in (_cached_price(coingecko_id, today),)
        if price is not None
    }
    missing_ids = [coingecko_id for coingecko_id in ids if coingecko_id not in cached]
    if not missing_ids:
        return cached

    payload = request_json(
        "/simple/price",
        {"ids": ",".join(missing_ids), "vs_currencies": "eur"},
    )
    if payload is None:
        return cached

    prices: dict[str, Decimal] = dict(cached)
    for coingecko_id in missing_ids:
        value = (payload.get(coingecko_id) or {}).get("eur") if isinstance(payload, dict) else None
        price = _to_decimal(value)
        if price is None:
            continue
        prices[coingecko_id] = price
        _upsert_price(coingecko_id, today, price, PRICE_SOURCE_CURRENT)
    return prices


def _url_for(path: str) -> str:
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{COINGECKO_BASE}/{path.lstrip('/')}"


def _record_call(source: str = SOURCE, day: str | None = None) -> None:
    log_date = day or date.today().isoformat()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO price_fetch_log (date, source, count)
            VALUES (?, ?, 1)
            ON CONFLICT(date, source) DO UPDATE SET count = count + 1
            """,
            (log_date, source),
        )
        conn.commit()
    finally:
        conn.close()


def _cached_price(coingecko_id: str, price_date: date) -> Decimal | None:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT eur, source FROM price_cache WHERE coingecko_id = ? AND date = ?",
            (coingecko_id, price_date.isoformat()),
        ).fetchone()
        if not row:
            return None
        if row["source"] == PRICE_SOURCE_CURRENT and price_date < date.today():
            return None
        return _to_decimal(row["eur"])
    finally:
        conn.close()


def _upsert_price(
    coingecko_id: str,
    price_date: date,
    eur: Decimal,
    source: str = PRICE_SOURCE_MARKET_CHART,
) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO price_cache (coingecko_id, date, eur, source, fetched_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(coingecko_id, date) DO UPDATE SET
                eur = excluded.eur,
                source = excluded.source,
                fetched_at = excluded.fetched_at
            """,
            (coingecko_id, price_date.isoformat(), str(eur), source, _utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def _daily_prices_from_market_chart(payload: dict, start: date, end: date) -> dict[date, Decimal]:
    latest_by_day: dict[date, tuple[int, Decimal]] = {}
    for point in payload.get("prices", []) if isinstance(payload, dict) else []:
        if not isinstance(point, list | tuple) or len(point) < 2:
            continue
        timestamp_ms, value = point[0], point[1]
        price = _to_decimal(value)
        if price is None:
            continue
        try:
            timestamp = int(timestamp_ms)
        except (TypeError, ValueError):
            continue
        day = datetime.fromtimestamp(timestamp // 1000, timezone.utc).date()
        if day < start or day > end:
            continue
        previous = latest_by_day.get(day)
        if previous is None or timestamp >= previous[0]:
            latest_by_day[day] = (timestamp, price)
    return {day: price for day, (_, price) in latest_by_day.items()}


def _date_span(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _unix_start(day: date) -> int:
    return int(datetime.combine(day, datetime_time.min, timezone.utc).timestamp())


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _wait_for_call_slot() -> None:
    if _last_call_at is None:
        return
    elapsed = time.monotonic() - _last_call_at
    remaining = MIN_CALL_INTERVAL - elapsed
    if remaining > 0:
        time.sleep(remaining)


def _remember_call_time() -> None:
    global _last_call_at
    _last_call_at = time.monotonic()


def _sleep_backoff(attempt: int) -> None:
    time.sleep(INITIAL_BACKOFF * (2 ** attempt))
