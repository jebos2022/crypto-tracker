import unittest
import sqlite3
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from core import prices


USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
FAKE_CONTRACT = "0x" + "9" * 40


class PriceHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.valuation_patch = patch.object(
            prices.token_valuation,
            "valuations_for_keys",
            side_effect=lambda keys: {
                key: prices.token_valuation.DEFAULT_VALUATION
                for key in keys
            },
        )
        self.valuation_patch.start()
        self.addCleanup(self.valuation_patch.stop)

    def test_eur_value_multiplies_amount_by_daily_price(self) -> None:
        with patch.object(prices.coingecko, "fetch_price", return_value=Decimal("2.50")) as fetch:
            value = prices.eur_value("ethereum", "4", date(2026, 1, 1))

        self.assertEqual(value, Decimal("10.00"))
        fetch.assert_called_once_with("ethereum", date(2026, 1, 1))

    def test_eur_value_returns_none_for_unknown_or_missing_price(self) -> None:
        self.assertIsNone(prices.eur_value(None, "4", date(2026, 1, 1)))
        with patch.object(prices.coingecko, "fetch_price", return_value=None):
            self.assertIsNone(prices.eur_value("ethereum", "4", date(2026, 1, 1)))

    def test_eur_balances_today_uses_one_current_price_call(self) -> None:
        rows = [
            {"chain": "ethereum", "asset": "ETH", "contract_address": None, "balance": Decimal("2")},
            {"chain": "ethereum", "asset": "USDC", "contract_address": USDC, "balance": Decimal("10")},
        ]

        with patch.object(
            prices.coingecko,
            "fetch_current_prices",
            return_value={"ethereum": Decimal("2000"), "usd-coin": Decimal("0.90")},
        ) as fetch:
            enriched = prices.eur_balances_today(rows)

        fetch.assert_called_once_with(["ethereum", "usd-coin"])
        self.assertEqual(enriched[0]["eur_value"], Decimal("4000"))
        self.assertEqual(enriched[1]["eur_value"], Decimal("9.00"))
        self.assertFalse(prices.has_unknown_eur(enriched))

    def test_eur_balances_today_marks_unknown_tokens(self) -> None:
        rows = [
            {
                "chain": "ethereum",
                "asset": "USDC",
                "contract_address": FAKE_CONTRACT,
                "balance": Decimal("10"),
            }
        ]

        with patch.object(prices.coingecko, "fetch_current_prices") as fetch:
            enriched = prices.eur_balances_today(rows)

        fetch.assert_not_called()
        self.assertIsNone(enriched[0]["coingecko_id"])
        self.assertIsNone(enriched[0]["eur_value"])
        self.assertTrue(enriched[0]["eur_missing"])

    def test_eur_balances_today_prices_canonical_identity_aliases(self) -> None:
        rows = [
            {
                "chain": "arbitrum",
                "asset": "ARB",
                "contract_address": "0x912ce59144191c1204e64559fe8253a0e49e6548",
                "balance": Decimal("2"),
            },
            {
                "chain": "beam",
                "asset": "WBEAM",
                "contract_address": "0xd51bfa777609213a653a2cd067c9a0132a2d316a",
                "balance": Decimal("1000"),
            },
            {
                "chain": "arbitrum",
                "asset": "ATH",
                "contract_address": "0xc87b37a581ec3257b734886d9d3a581f5a9d056c",
                "balance": Decimal("3"),
            },
        ]

        with patch.object(
            prices.coingecko,
            "fetch_current_prices",
            return_value={
                "arbitrum": Decimal("1.25"),
                "beam-2": Decimal("0.02"),
                "aethir": Decimal("0.50"),
            },
        ) as fetch:
            enriched = prices.eur_balances_today(rows)

        fetch.assert_called_once_with(["aethir", "arbitrum", "beam-2"])
        self.assertEqual(enriched[0]["coingecko_id"], "arbitrum")
        self.assertEqual(enriched[0]["canonical_asset"], "ARB")
        self.assertEqual(enriched[0]["eur_value"], Decimal("2.50"))
        self.assertEqual(enriched[1]["coingecko_id"], "beam-2")
        self.assertEqual(enriched[1]["canonical_asset"], "BEAM")
        self.assertEqual(enriched[1]["eur_value"], Decimal("20.00"))
        self.assertEqual(enriched[2]["coingecko_id"], "aethir")
        self.assertEqual(enriched[2]["canonical_asset"], "ATH")
        self.assertEqual(enriched[2]["eur_value"], Decimal("1.50"))

    def test_eur_balances_today_does_not_price_fake_known_symbols(self) -> None:
        rows = [
            {"chain": "arbitrum", "asset": "ARB", "contract_address": FAKE_CONTRACT, "balance": Decimal("1")},
            {"chain": "beam", "asset": "BEAM", "contract_address": FAKE_CONTRACT, "balance": Decimal("1")},
            {"chain": "ethereum", "asset": "ATH", "contract_address": FAKE_CONTRACT, "balance": Decimal("1")},
            {"chain": "ethereum", "asset": "OPN", "contract_address": FAKE_CONTRACT, "balance": Decimal("1")},
            {"chain": "arbitrum", "asset": "PEAR", "contract_address": FAKE_CONTRACT, "balance": Decimal("1")},
        ]

        with patch.object(prices.coingecko, "fetch_current_prices") as fetch:
            enriched = prices.eur_balances_today(rows)

        fetch.assert_not_called()
        self.assertTrue(all(row["coingecko_id"] is None for row in enriched))
        self.assertTrue(all(row["eur_value"] is None for row in enriched))

    def test_eur_balances_today_handles_price_client_error(self) -> None:
        rows = [
            {"chain": "ethereum", "asset": "ETH", "contract_address": None, "balance": Decimal("2")}
        ]

        with patch.object(
            prices.coingecko,
            "fetch_current_prices",
            side_effect=prices.coingecko.CoinGeckoError("temporary"),
        ):
            enriched = prices.eur_balances_today(rows)

        self.assertIsNone(enriched[0]["eur_value"])
        self.assertTrue(enriched[0]["eur_missing"])

    def test_eur_balances_today_wrapper_is_not_directly_priced(self) -> None:
        rows = [
            {
                "chain": "arbitrum",
                "asset": "stPEAR",
                "contract_address": "0xce3be5204017bb1bd279937f92df09fd7f539b92",
                "balance": Decimal("10"),
            }
        ]

        with patch.object(prices.coingecko, "fetch_current_prices") as fetch:
            enriched = prices.eur_balances_today(rows)

        fetch.assert_not_called()
        self.assertIsNone(enriched[0]["coingecko_id"])
        self.assertEqual(enriched[0]["canonical_asset"], "PEAR")
        self.assertIsNone(enriched[0]["eur_value"])
        self.assertTrue(enriched[0]["eur_missing"])

    def test_manual_zero_balance_skips_price_fetch_and_returns_zero(self) -> None:
        rows = [
            {"chain": "ethereum", "asset": "ETH", "contract_address": None, "balance": Decimal("2")}
        ]
        valuation = prices.token_valuation.TokenValuation(
            prices.token_valuation.VALUATION_MANUAL_ZERO,
            date.today(),
            "Project gestopt",
        )

        with (
            patch.object(
                prices.token_valuation,
                "valuations_for_keys",
                return_value={("ethereum", "native:ETH"): valuation},
            ),
            patch.object(prices.coingecko, "fetch_current_prices") as fetch,
        ):
            enriched = prices.eur_balances_today(rows)

        fetch.assert_not_called()
        self.assertEqual(enriched[0]["eur_value"], Decimal("0"))
        self.assertFalse(enriched[0]["eur_missing"])
        self.assertTrue(enriched[0]["valuation_manual"])

    def test_manual_zero_transaction_applies_from_effective_date(self) -> None:
        rows = [
            {
                "chain": "ethereum",
                "asset": "ETH",
                "contract_address": None,
                "amount": "1",
                "timestamp": "2026-01-01T12:00:00",
            },
            {
                "chain": "ethereum",
                "asset": "ETH",
                "contract_address": None,
                "amount": "1",
                "timestamp": "2026-01-03T12:00:00",
            },
        ]
        valuation = prices.token_valuation.TokenValuation(
            prices.token_valuation.VALUATION_MANUAL_ZERO,
            date(2026, 1, 2),
            "",
        )

        with (
            patch.object(
                prices.token_valuation,
                "valuations_for_keys",
                return_value={("ethereum", "native:ETH"): valuation},
            ),
            patch.object(
                prices.coingecko,
                "fetch_price_range",
                return_value={date(2026, 1, 1): Decimal("2000")},
            ) as fetch,
        ):
            enriched = prices.eur_transactions(rows)

        fetch.assert_called_once_with("ethereum", date(2026, 1, 1), date(2026, 1, 1))
        self.assertEqual(enriched[0]["eur_value"], Decimal("2000"))
        self.assertEqual(enriched[1]["eur_value"], Decimal("0"))
        self.assertTrue(enriched[1]["valuation_manual"])

    def test_eur_transactions_prefetches_once_per_token_year(self) -> None:
        rows = [
            {
                "chain": "ethereum",
                "asset": "ETH",
                "contract_address": None,
                "amount": "1",
                "timestamp": "2026-01-10T12:00:00",
            },
            {
                "chain": "ethereum",
                "asset": "ETH",
                "contract_address": None,
                "amount": "-0.5",
                "timestamp": "2026-02-01T08:00:00",
            },
        ]
        price_map = {
            date(2026, 1, 10): Decimal("2000"),
            date(2026, 2, 1): Decimal("2200"),
        }

        with patch.object(prices.coingecko, "fetch_price_range", return_value=price_map) as fetch:
            enriched = prices.eur_transactions(rows)

        fetch.assert_called_once_with("ethereum", date(2026, 1, 10), date(2026, 2, 1))
        self.assertEqual(enriched[0]["eur_value"], Decimal("2000"))
        self.assertEqual(enriched[1]["eur_value"], Decimal("-1100.0"))

    def test_eur_transactions_invalid_timestamp_does_not_fetch(self) -> None:
        rows = [
            {
                "chain": "ethereum",
                "asset": "ETH",
                "contract_address": None,
                "amount": "1",
                "timestamp": "niet-een-datum",
            }
        ]

        with patch.object(prices.coingecko, "fetch_price_range") as fetch:
            enriched = prices.eur_transactions(rows)

        fetch.assert_not_called()
        self.assertIsNone(enriched[0]["eur_value"])

    def test_balance_at_sums_accepted_rows_up_to_date(self) -> None:
        with TempPriceDb(prices) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_tx("in", "2026-01-01T10:00:00", "ethereum", "ETH", None, "2")
            db.insert_tx("out", "2026-01-02T10:00:00", "ethereum", "ETH", None, "-0.5")
            db.insert_tx("future", "2026-01-03T10:00:00", "ethereum", "ETH", None, "10")

            rows = prices.balance_at(date(2026, 1, 2))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["balance"], Decimal("1.5"))

    def test_snapshot_for_year_returns_open_and_close_eur_values(self) -> None:
        with TempPriceDb(prices) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_tx("open", "2025-12-31T23:00:00", "ethereum", "ETH", None, "1")
            db.insert_tx("buy", "2026-06-01T10:00:00", "ethereum", "ETH", None, "2")
            price_maps = {
                date(2026, 1, 1): Decimal("2000"),
                date(2026, 12, 31): Decimal("2500"),
            }

            with patch.object(
                prices.coingecko,
                "fetch_price_range",
                return_value=price_maps,
            ) as fetch:
                rows = prices.snapshot_for_year(2026)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["open_balance"], Decimal("1"))
        self.assertEqual(rows[0]["open_eur"], Decimal("2000"))
        self.assertEqual(rows[0]["close_balance"], Decimal("3"))
        self.assertEqual(rows[0]["close_eur"], Decimal("7500"))
        self.assertFalse(rows[0]["incomplete"])
        fetch.assert_called_once_with("ethereum", date(2026, 1, 1), date(2026, 12, 31))

    def test_snapshot_for_year_treats_missing_zero_balance_side_as_zero_eur(self) -> None:
        with TempPriceDb(prices) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_tx("open", "2025-12-31T23:00:00", "ethereum", "ETH", None, "1")
            db.insert_tx("sell", "2026-06-01T10:00:00", "ethereum", "ETH", None, "-1")

            with patch.object(
                prices.coingecko,
                "fetch_price_range",
                return_value={date(2026, 1, 1): Decimal("2000")},
            ):
                rows = prices.snapshot_for_year(2026)

        self.assertEqual(rows[0]["open_eur"], Decimal("2000"))
        self.assertEqual(rows[0]["close_balance"], Decimal("0"))
        self.assertEqual(rows[0]["close_eur"], Decimal("0"))
        self.assertFalse(rows[0]["incomplete"])

    def test_snapshot_for_year_treats_missing_open_balance_side_as_zero_eur(self) -> None:
        with TempPriceDb(prices) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_tx("buy", "2026-06-01T10:00:00", "ethereum", "ETH", None, "1")

            with patch.object(
                prices.coingecko,
                "fetch_price_range",
                return_value={date(2026, 12, 31): Decimal("2500")},
            ):
                rows = prices.snapshot_for_year(2026)

        self.assertEqual(rows[0]["open_balance"], Decimal("0"))
        self.assertEqual(rows[0]["open_eur"], Decimal("0"))
        self.assertEqual(rows[0]["close_eur"], Decimal("2500"))
        self.assertFalse(rows[0]["incomplete"])

    def test_snapshot_price_ids_estimates_one_call_per_token_year(self) -> None:
        with TempPriceDb(prices) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_review("ethereum", "USDC", USDC, accepted=1)
            db.insert_tx("eth", "2026-01-01T10:00:00", "ethereum", "ETH", None, "1")
            db.insert_tx("usdc", "2026-01-01T10:00:00", "ethereum", "USDC", USDC, "10")

            ids = prices.snapshot_price_ids(2026)

        self.assertEqual(ids, ["ethereum", "usd-coin"])


class TempPriceDb:
    def __init__(self, module):
        self.module = module
        self.path = Path(tempfile.mkdtemp()) / "prices.db"
        self.original_get_connection = module.get_connection

    def __enter__(self):
        self.module.get_connection = self.conn
        with self.conn() as conn:
            conn.executescript(
                """
                CREATE TABLE wallets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    address TEXT NOT NULL UNIQUE
                );
                CREATE TABLE transactions (
                    id TEXT PRIMARY KEY,
                    wallet_id INTEGER NOT NULL,
                    chain TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    block_number INTEGER NOT NULL DEFAULT 0,
                    tx_hash TEXT NOT NULL,
                    from_address TEXT,
                    to_address TEXT,
                    type TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    contract_address TEXT,
                    amount TEXT NOT NULL,
                    source TEXT NOT NULL,
                    method_id TEXT,
                    method_name TEXT
                );
                CREATE TABLE token_review (
                    wallet_id INTEGER NOT NULL,
                    chain TEXT NOT NULL,
                    token_key TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    contract_address TEXT,
                    accepted INTEGER NOT NULL DEFAULT 0,
                    valuation_status TEXT NOT NULL DEFAULT 'active',
                    valuation_effective_date TEXT,
                    valuation_reason TEXT,
                    PRIMARY KEY (wallet_id, chain, token_key)
                );
                """
            )
        return self

    def __exit__(self, exc_type, exc, tb):
        self.module.get_connection = self.original_get_connection

    def conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def insert_wallet(self) -> None:
        with self.conn() as conn:
            conn.execute(
                "INSERT INTO wallets (id, name, address) VALUES (1, 'main', '0x' || printf('%040d', 1))"
            )

    def insert_review(self, chain: str, asset: str, contract: str | None, accepted: int) -> None:
        token_key = contract.lower() if contract else f"native:{asset}"
        with self.conn() as conn:
            conn.execute(
                """
                INSERT INTO token_review (wallet_id, chain, token_key, asset, contract_address, accepted)
                VALUES (1, ?, ?, ?, ?, ?)
                """,
                (chain, token_key, asset, contract, accepted),
            )

    def insert_tx(
        self,
        tx_id: str,
        timestamp: str,
        chain: str,
        asset: str,
        contract: str | None,
        amount: str,
    ) -> None:
        with self.conn() as conn:
            conn.execute(
                """
                INSERT INTO transactions
                    (id, wallet_id, chain, timestamp, block_number, tx_hash,
                     type, asset, contract_address, amount, source)
                VALUES (?, 1, ?, ?, 1, ?, 'TRANSFER_IN', ?, ?, ?, 'tokentx')
                """,
                (tx_id, chain, timestamp, "0x" + tx_id[:1] * 64, asset, contract, amount),
            )


if __name__ == "__main__":
    unittest.main()
