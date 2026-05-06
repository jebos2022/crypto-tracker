import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import db, wallets


WALLET_1 = "0x" + "1" * 40
WALLET_2 = "0x" + "2" * 40


class WalletCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "wallets.db"

        def conn_factory() -> sqlite3.Connection:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            return conn

        self.conn_factory = conn_factory
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        conn.commit()
        conn.close()

        self.original_get_connection = wallets.get_connection
        self.original_create_backup = wallets.create_backup
        wallets.get_connection = conn_factory
        self.backup_calls = 0

        def fake_backup():
            self.backup_calls += 1
            return None

        wallets.create_backup = fake_backup

    def tearDown(self) -> None:
        wallets.get_connection = self.original_get_connection
        wallets.create_backup = self.original_create_backup

    def test_add_wallet_normalizes_address_and_default_name(self) -> None:
        wallets.add_wallet("", WALLET_1.upper())

        rows = wallets.get_wallets_for_fetch()

        self.assertEqual(rows, [{
            "id": 1,
            "name": WALLET_1[:14] + "...",
            "address": WALLET_1,
        }])

    def test_add_wallet_raises_on_duplicate_address(self) -> None:
        wallets.add_wallet("main", WALLET_1)

        with self.assertRaises(sqlite3.IntegrityError):
            wallets.add_wallet("duplicate", WALLET_1.upper())

    def test_get_wallets_with_fetch_state_uses_latest_endpoint_timestamp(self) -> None:
        wallets.add_wallet("main", WALLET_1)
        conn = self.conn_factory()
        conn.executemany(
            """
            INSERT INTO wallet_chain_state
                (wallet_id, chain, endpoint, last_block, last_fetched)
            VALUES (1, 'ethereum', ?, 1, ?)
            """,
            [
                ("tokentx", "2026-01-01T10:00:00"),
                ("txlist", "2026-01-02T10:00:00"),
            ],
        )
        conn.commit()
        conn.close()

        rows = wallets.get_wallets_with_fetch_state()

        self.assertEqual(rows[0]["last_fetched"], "2026-01-02T10:00:00")

    def test_delete_wallet_creates_backup_and_cascades_related_rows(self) -> None:
        wallets.add_wallet("main", WALLET_1)
        conn = self.conn_factory()
        conn.execute(
            """
            INSERT INTO transactions
                (id, wallet_id, chain, timestamp, block_number, tx_hash,
                 type, asset, amount, source)
            VALUES ('tx1', 1, 'ethereum', '2026-01-01T00:00:00', 1,
                    '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                    'TRANSFER_IN', 'ETH', '1', 'txlist')
            """
        )
        conn.execute(
            """
            INSERT INTO token_review
                (wallet_id, chain, token_key, asset, accepted)
            VALUES (1, 'ethereum', 'native:ETH', 'ETH', 1)
            """
        )
        conn.commit()
        conn.close()

        wallets.delete_wallet(1)

        conn = self.conn_factory()
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("wallets", "transactions", "token_review")
        }
        conn.close()

        self.assertEqual(self.backup_calls, 1)
        self.assertEqual(counts, {"wallets": 0, "transactions": 0, "token_review": 0})


class DbTransactionHelperTests(unittest.TestCase):
    def test_clear_transactions_keeps_wallets_and_token_meta(self) -> None:
        path = Path(tempfile.mkdtemp()) / "portfolio.db"
        original_path = db.DB_PATH
        db.DB_PATH = path
        try:
            conn = db.get_connection()
            conn.executescript(db.SCHEMA_SQL)
            conn.execute("INSERT INTO wallets (id, name, address) VALUES (1, 'main', ?)", (WALLET_2,))
            conn.execute(
                """
                INSERT INTO transactions
                    (id, wallet_id, chain, timestamp, block_number, tx_hash,
                     type, asset, amount, source)
                VALUES ('tx1', 1, 'ethereum', '2026-01-01T00:00:00', 1,
                        '0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                        'TRANSFER_IN', 'ETH', '1', 'txlist')
                """
            )
            conn.execute(
                """
                INSERT INTO wallet_chain_state
                    (wallet_id, chain, endpoint, last_block)
                VALUES (1, 'ethereum', 'txlist', 10)
                """
            )
            conn.execute(
                """
                INSERT INTO token_review
                    (wallet_id, chain, token_key, asset, accepted)
                VALUES (1, 'ethereum', 'native:ETH', 'ETH', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO token_meta (chain, contract_address, symbol, decimals)
                VALUES ('ethereum', '0xcccccccccccccccccccccccccccccccccccccccc', 'TST', 18)
                """
            )
            conn.commit()
            conn.close()

            self.assertEqual(db.transaction_count(), 1)
            db.clear_transactions()
            after_count = db.transaction_count()

            conn = db.get_connection()
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("wallets", "transactions", "wallet_chain_state", "token_review", "token_meta")
            }
            conn.close()
        finally:
            db.DB_PATH = original_path

        self.assertEqual(after_count, 0)
        self.assertEqual(counts, {
            "wallets": 1,
            "transactions": 0,
            "wallet_chain_state": 0,
            "token_review": 0,
            "token_meta": 1,
        })


if __name__ == "__main__":
    unittest.main()
