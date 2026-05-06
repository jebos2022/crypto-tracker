import sqlite3
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from core import balance_check, db


WALLET = "0x" + "1" * 40
OTHER = "0x" + "2" * 40
USDC = "0x" + "3" * 40
RENAMED_NATIVE = "0x" + "4" * 40


class BalanceCheckTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "balance-check.db"

        def conn_factory() -> sqlite3.Connection:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            return conn

        self.conn_factory = conn_factory
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        conn.executescript(db.INDICES_SQL)
        conn.execute(
            "INSERT INTO wallets (id, name, address) VALUES (?, ?, ?)",
            (1, "main", WALLET),
        )
        conn.commit()
        conn.close()

        self.original_get_connection = balance_check.get_connection
        self.original_fetch_native = balance_check.api.fetch_native_balance
        self.original_fetch_token = balance_check.api.fetch_token_balance
        balance_check.get_connection = conn_factory

    def tearDown(self) -> None:
        balance_check.get_connection = self.original_get_connection
        balance_check.api.fetch_native_balance = self.original_fetch_native
        balance_check.api.fetch_token_balance = self.original_fetch_token

    def _insert_tx(
        self,
        asset: str,
        amount: str,
        contract_address: str | None,
        tx_hash: str,
    ) -> None:
        conn = self.conn_factory()
        token_key = contract_address.lower() if contract_address else f"native:{asset}"
        conn.execute(
            """
            INSERT OR IGNORE INTO token_review
                (wallet_id, chain, token_key, asset, contract_address, accepted)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (1, "ethereum", token_key, asset, contract_address),
        )
        conn.execute(
            """
            INSERT INTO transactions
                (id, wallet_id, chain, timestamp, block_number, tx_hash,
                 from_address, to_address, type, asset, contract_address,
                 amount, source)
            VALUES (?, 1, 'ethereum', '2026-01-01T00:00:00', 1, ?,
                    ?, ?, 'TRANSFER_IN', ?, ?, ?, 'txlist')
            """,
            (tx_hash, tx_hash, OTHER, WALLET, asset, contract_address, amount),
        )
        conn.commit()
        conn.close()

    def _insert_token_meta(self, contract_address: str, decimals: int) -> None:
        conn = self.conn_factory()
        conn.execute(
            """
            INSERT INTO token_meta (chain, contract_address, symbol, decimals, last_seen)
            VALUES ('ethereum', ?, 'TST', ?, '2026-01-01T00:00:00')
            """,
            (contract_address.lower(), decimals),
        )
        conn.commit()
        conn.close()

    def test_native_balance_uses_native_endpoint_and_decimal_delta(self) -> None:
        self._insert_tx("ETH", "1.5", None, "eth-in")
        balance_check.api.fetch_native_balance = lambda _address, _chain: "1500000000000000000"
        balance_check.api.fetch_token_balance = self.fail

        rows = balance_check.verify_balances()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].computed, Decimal("1.5"))
        self.assertEqual(rows[0].onchain, Decimal("1.5"))
        self.assertEqual(rows[0].delta, Decimal("0.0"))
        self.assertTrue(rows[0].decimals_known)
        self.assertIsNone(rows[0].error)

    def test_computed_balance_sums_multiple_rows_exactly(self) -> None:
        self._insert_tx("ETH", "0.1", None, "eth-in-1")
        self._insert_tx("ETH", "0.2", None, "eth-in-2")
        balance_check.api.fetch_native_balance = lambda _address, _chain: "300000000000000000"
        balance_check.api.fetch_token_balance = self.fail

        rows = balance_check.verify_balances()

        self.assertEqual(rows[0].computed, Decimal("0.3"))
        self.assertEqual(rows[0].onchain, Decimal("0.3"))
        self.assertEqual(rows[0].delta, Decimal("0.0"))

    def test_erc20_balance_uses_token_endpoint_and_token_meta_decimals(self) -> None:
        self._insert_tx("USDC", "12.34", USDC, "usdc-in")
        self._insert_token_meta(USDC, 6)
        balance_check.api.fetch_native_balance = self.fail
        balance_check.api.fetch_token_balance = lambda _address, contract, _chain: (
            "12340000" if contract == USDC else self.fail("wrong contract")
        )

        rows = balance_check.verify_balances()

        self.assertEqual(rows[0].asset, "USDC")
        self.assertEqual(rows[0].onchain, Decimal("12.34"))
        self.assertEqual(rows[0].delta, Decimal("0.00"))
        self.assertTrue(rows[0].decimals_known)

    def test_renamed_native_token_is_checked_as_erc20(self) -> None:
        self._insert_tx("ETH-0x4444", "2", RENAMED_NATIVE, "renamed-native-in")
        self._insert_token_meta(RENAMED_NATIVE, 18)
        balance_check.api.fetch_native_balance = self.fail
        balance_check.api.fetch_token_balance = lambda _address, _contract, _chain: "2000000000000000000"

        rows = balance_check.verify_balances()

        self.assertEqual(rows[0].asset, "ETH-0x4444")
        self.assertEqual(rows[0].onchain, Decimal("2"))
        self.assertEqual(rows[0].delta, Decimal("0"))

    def test_missing_token_decimals_reports_raw_onchain_without_delta(self) -> None:
        self._insert_tx("TST", "7", USDC, "unknown-decimals-in")
        balance_check.api.fetch_native_balance = self.fail
        balance_check.api.fetch_token_balance = lambda _address, _contract, _chain: "7000000"

        rows = balance_check.verify_balances()

        self.assertEqual(rows[0].onchain, Decimal("7000000"))
        self.assertIsNone(rows[0].delta)
        self.assertFalse(rows[0].decimals_known)

    def test_api_error_is_reported_on_row(self) -> None:
        self._insert_tx("ETH", "1", None, "eth-error")

        def raise_timeout(_address, _chain):
            raise TimeoutError("boom")

        balance_check.api.fetch_native_balance = raise_timeout

        rows = balance_check.verify_balances()

        self.assertIsNone(rows[0].onchain)
        self.assertIsNone(rows[0].delta)
        self.assertIn("TimeoutError: boom", rows[0].error)


if __name__ == "__main__":
    unittest.main()
