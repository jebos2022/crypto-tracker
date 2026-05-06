import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from core import rendement
from core.models import GAS_FEE, TRANSFER_IN, TRANSFER_OUT


class RendementTests(unittest.TestCase):
    def test_compute_year_uses_snapshot_flow_formula_and_separate_gas(self) -> None:
        with TempRendementDb(rendement) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_tx("buy", "2026-02-01T10:00:00", TRANSFER_IN, "ETH", None, "0.2")
            db.insert_tx("sell", "2026-06-01T10:00:00", TRANSFER_OUT, "ETH", None, "-0.1")
            db.insert_tx("gas", "2026-06-01T10:00:01", GAS_FEE, "ETH", None, "-0.01", "txlist")

            with (
                patch.object(rendement, "snapshot_for_year", return_value=[
                    {
                        "wallet": "main",
                        "chain": "ethereum",
                        "asset": "ETH",
                        "contract_address": None,
                        "open_balance": Decimal("0.5"),
                        "open_eur": Decimal("1000"),
                        "close_balance": Decimal("0.6"),
                        "close_eur": Decimal("1500"),
                    }
                ]),
                patch.object(rendement, "eur_transactions", side_effect=_priced_rows({
                    "buy": Decimal("200"),
                    "sell": Decimal("-150"),
                    "gas": Decimal("-10"),
                })),
            ):
                rows = rendement.compute_year(2026)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["in_eur"], Decimal("200"))
        self.assertEqual(rows[0]["out_eur"], Decimal("150"))
        self.assertEqual(rows[0]["gas_eur"], Decimal("10"))
        self.assertEqual(rows[0]["netto_eur"], Decimal("450"))
        self.assertFalse(rows[0]["incomplete"])

    def test_compute_year_handles_token_bought_and_sold_inside_year(self) -> None:
        with TempRendementDb(rendement) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_tx("buy", "2026-03-01T10:00:00", TRANSFER_IN, "ETH", None, "1")
            db.insert_tx("sell", "2026-04-01T10:00:00", TRANSFER_OUT, "ETH", None, "-1")

            with (
                patch.object(rendement, "snapshot_for_year", return_value=[]),
                patch.object(rendement, "eur_transactions", side_effect=_priced_rows({
                    "buy": Decimal("1000"),
                    "sell": Decimal("-1200"),
                })),
            ):
                rows = rendement.compute_year(2026)

        self.assertEqual(rows[0]["open_eur"], Decimal("0"))
        self.assertEqual(rows[0]["close_eur"], Decimal("0"))
        self.assertEqual(rows[0]["netto_eur"], Decimal("200"))

    def test_compute_year_marks_missing_transaction_price_incomplete(self) -> None:
        with TempRendementDb(rendement) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_tx("buy", "2026-03-01T10:00:00", TRANSFER_IN, "ETH", None, "1")

            with (
                patch.object(rendement, "snapshot_for_year", return_value=[]),
                patch.object(rendement, "eur_transactions", side_effect=_priced_rows({
                    "buy": None,
                })),
            ):
                rows = rendement.compute_year(2026)

        self.assertIsNone(rows[0]["in_eur"])
        self.assertIsNone(rows[0]["netto_eur"])
        self.assertTrue(rows[0]["incomplete"])

    def test_compute_year_handles_snapshot_balance_without_year_transactions(self) -> None:
        with TempRendementDb(rendement) as db:
            db.insert_wallet()

            with (
                patch.object(rendement, "snapshot_for_year", return_value=[
                    {
                        "wallet": "main",
                        "chain": "ethereum",
                        "asset": "ETH",
                        "contract_address": None,
                        "open_balance": Decimal("1"),
                        "open_eur": Decimal("100"),
                        "close_balance": Decimal("1"),
                        "close_eur": Decimal("150"),
                    }
                ]),
                patch.object(rendement, "eur_transactions") as tx_prices,
            ):
                rows = rendement.compute_year(2026)

        tx_prices.assert_not_called()
        self.assertEqual(rows[0]["netto_eur"], Decimal("50"))
        self.assertFalse(rows[0]["incomplete"])

    def test_price_ids_for_year_estimates_transaction_price_ids_without_symbol_fallback(self) -> None:
        fake_arb = "0x" + "9" * 40
        with TempRendementDb(rendement) as db:
            db.insert_wallet()
            db.insert_review("ethereum", "ETH", None, accepted=1)
            db.insert_review("arbitrum", "ARB", fake_arb, accepted=1)
            db.insert_tx("eth", "2026-03-01T10:00:00", TRANSFER_IN, "ETH", None, "1")
            db.insert_tx("fake", "2026-03-01T11:00:00", TRANSFER_IN, "ARB", fake_arb, "1", chain="arbitrum")

            ids = rendement.price_ids_for_year(2026)

        self.assertEqual(ids, ["ethereum"])


def _priced_rows(values_by_id: dict[str, Decimal | None]):
    def price(rows: list[dict]) -> list[dict]:
        return [
            {
                **row,
                "eur_value": values_by_id[row["id"]],
                "eur_missing": values_by_id[row["id"]] is None,
            }
            for row in rows
        ]

    return price


class TempRendementDb:
    def __init__(self, module):
        self.module = module
        self.path = Path(tempfile.mkdtemp()) / "rendement.db"
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
        tx_type: str,
        asset: str,
        contract: str | None,
        amount: str,
        source: str = "tokentx",
        chain: str = "ethereum",
    ) -> None:
        with self.conn() as conn:
            conn.execute(
                """
                INSERT INTO transactions
                    (id, wallet_id, chain, timestamp, block_number, tx_hash,
                     type, asset, contract_address, amount, source)
                VALUES (?, 1, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                """,
                (tx_id, chain, timestamp, _tx_hash(tx_id), tx_type, asset, contract, amount, source),
            )


def _tx_hash(tx_id: str) -> str:
    return "0x" + tx_id.encode("utf-8").hex().ljust(64, "0")[:64]


if __name__ == "__main__":
    unittest.main()
