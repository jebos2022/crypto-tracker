import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import db, transactions
from core.ledger import logical_tx_groups


HASH = "0x" + "a" * 64
OTHER_HASH = "0x" + "b" * 64
WALLET = "0x" + "1" * 40
OTHER = "0x" + "2" * 40
GET_CONTRACT = "0x" + "3" * 40
RARE_CONTRACT = "0x" + "4" * 40


class TransactionQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "transactions.db"

        def conn_factory() -> sqlite3.Connection:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            return conn

        self.conn_factory = conn_factory
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        conn.executescript(db.INDICES_SQL)
        conn.execute("INSERT INTO wallets (id, name, address) VALUES (1, 'Main', ?)", (WALLET,))
        conn.commit()
        conn.close()

        self.original_get_connection = transactions.get_connection
        transactions.get_connection = conn_factory

    def tearDown(self) -> None:
        transactions.get_connection = self.original_get_connection

    def _accept_token(self, asset: str, contract: str | None = None, accepted: int = 1) -> None:
        token_key = contract.lower() if contract else f"native:{asset}"
        conn = self.conn_factory()
        conn.execute(
            """
            INSERT INTO token_review
                (wallet_id, chain, token_key, asset, contract_address, accepted)
            VALUES (1, 'ethereum', ?, ?, ?, ?)
            """,
            (token_key, asset, contract, accepted),
        )
        conn.commit()
        conn.close()

    def _insert_tx(
        self,
        tx_id: str,
        tx_hash: str,
        asset: str,
        amount: str,
        tx_type: str,
        source: str,
        contract: str | None = None,
        timestamp: str = "2026-01-01T12:00:00",
    ) -> None:
        conn = self.conn_factory()
        conn.execute(
            """
            INSERT INTO transactions
                (id, wallet_id, chain, timestamp, block_number, tx_hash,
                 from_address, to_address, type, asset, contract_address,
                 amount, source, method_id, method_name)
            VALUES (?, 1, 'ethereum', ?, 10, ?, ?, ?, ?, ?, ?, ?, ?, '0x12345678', 'swapExactETHForTokens()')
            """,
            (tx_id, timestamp, tx_hash, WALLET, OTHER, tx_type, asset, contract, amount, source),
        )
        conn.commit()
        conn.close()

    def test_filter_options_only_include_accepted_activity(self) -> None:
        self._accept_token("ETH")
        self._accept_token("GET", GET_CONTRACT)
        self._accept_token("RARE", RARE_CONTRACT, accepted=0)
        self._insert_tx("eth", HASH, "ETH", "-1", "TRANSFER_OUT", "txlist")
        self._insert_tx("get", HASH, "GET", "100", "TRANSFER_IN", "tokentx", GET_CONTRACT)
        self._insert_tx("rare", OTHER_HASH, "RARE", "1", "TRANSFER_IN", "tokentx", RARE_CONTRACT)

        self.assertEqual(transactions.get_transaction_wallets(), [{"id": 1, "name": "Main"}])
        self.assertEqual(transactions.get_transaction_chains(None), ["ethereum"])
        self.assertEqual(transactions.get_transaction_years(None, "ethereum"), [2026])
        self.assertEqual(transactions.get_transaction_assets(None, "ethereum", 2026), ["ETH", "GET"])

    def test_asset_filter_returns_full_transaction_context_for_grouped_view_and_csv(self) -> None:
        self._accept_token("ETH")
        self._accept_token("GET", GET_CONTRACT)
        self._insert_tx("eth-out", HASH, "ETH", "-1", "TRANSFER_OUT", "txlist")
        self._insert_tx("gas", f"{HASH}_fee", "ETH", "-0.003", "GAS_FEE", "txlist")
        self._insert_tx("get-in", HASH, "GET", "100", "TRANSFER_IN", "tokentx", GET_CONTRACT)
        self._insert_tx("other-eth", OTHER_HASH, "ETH", "-2", "TRANSFER_OUT", "txlist")

        rows = transactions.get_transactions(None, "ethereum", 2026, "GET", descending=False)
        groups = logical_tx_groups(rows, asset_filter="GET")

        self.assertEqual([row["asset"] for row in rows], ["ETH", "ETH", "GET"])
        self.assertEqual({row["tx_hash"] for row in rows}, {HASH, f"{HASH}_fee"})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["row_count"], 3)
        self.assertEqual(groups[0]["assets"], ["ETH", "GET"])
        self.assertTrue(all("method_id" in row and "source" in row for row in rows))

    def test_asset_filter_returns_no_rows_for_missing_asset(self) -> None:
        self._accept_token("ETH")
        self._insert_tx("eth", HASH, "ETH", "-1", "TRANSFER_OUT", "txlist")

        rows = transactions.get_transactions(None, "ethereum", 2026, "GET", descending=False)

        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
