import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import db, token_review


class DbMigrationTests(unittest.TestCase):
    def test_price_schema_created_idempotently(self) -> None:
        path = Path(tempfile.mkdtemp()) / "portfolio.db"

        original_path = db.DB_PATH
        db.DB_PATH = path
        try:
            db.init_db()
            db.init_db()
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            price_cache_cols = conn.execute("PRAGMA table_info(price_cache)").fetchall()
            price_fetch_log_cols = conn.execute("PRAGMA table_info(price_fetch_log)").fetchall()
            price_cache_indices = conn.execute("PRAGMA index_list(price_cache)").fetchall()
            token_review_cols = conn.execute("PRAGMA table_info(token_review)").fetchall()
            conn.close()
        finally:
            db.DB_PATH = original_path

        self.assertEqual(
            [row["name"] for row in price_cache_cols],
            ["coingecko_id", "date", "eur", "source", "fetched_at"],
        )
        self.assertEqual(
            [row["name"] for row in price_fetch_log_cols],
            ["date", "source", "count"],
        )
        self.assertEqual(
            [row["name"] for row in price_cache_cols if row["pk"]],
            ["coingecko_id", "date"],
        )
        self.assertEqual(
            [row["name"] for row in price_fetch_log_cols if row["pk"]],
            ["date", "source"],
        )
        self.assertIn(
            "idx_price_cache_date",
            [row["name"] for row in price_cache_indices],
        )
        self.assertIn("valuation_status", [row["name"] for row in token_review_cols])
        self.assertIn("valuation_effective_date", [row["name"] for row in token_review_cols])
        self.assertIn("valuation_reason", [row["name"] for row in token_review_cols])

    def test_old_asset_keyed_token_review_migrates_to_contract_keys(self) -> None:
        path = Path(tempfile.mkdtemp()) / "portfolio.db"
        conn = sqlite3.connect(path)
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
                method_name TEXT,
                UNIQUE (tx_hash, wallet_id, source)
            );
            CREATE TABLE token_review (
                wallet_id INTEGER NOT NULL,
                chain TEXT NOT NULL,
                asset TEXT NOT NULL,
                contract_address TEXT,
                accepted INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (wallet_id, chain, asset)
            );
            INSERT INTO wallets (id, name, address)
            VALUES (1, 'main', '0x1111111111111111111111111111111111111111');
            INSERT INTO transactions
                (id, wallet_id, chain, timestamp, block_number, tx_hash,
                 type, asset, contract_address, amount, source)
            VALUES
                ('tx1', 1, 'ethereum', '2026-04-30T10:00:00', 1,
                 '0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                 'TRANSFER_IN', 'USDC',
                 '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48',
                 '10', 'tokentx');
            INSERT INTO token_review
            VALUES (1, 'ethereum', 'USDC', '0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48', 0);
            """
        )
        conn.commit()
        conn.close()

        original_path = db.DB_PATH
        db.DB_PATH = path
        try:
            db.init_db()
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT token_key, asset, accepted, review_status FROM token_review"
            ).fetchall()
            conn.close()
        finally:
            db.DB_PATH = original_path

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["token_key"], "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48")
        self.assertEqual(rows[0]["asset"], "USDC")
        self.assertEqual(rows[0]["accepted"], 1)
        self.assertEqual(rows[0]["review_status"], token_review.STATUS_SAFE)


if __name__ == "__main__":
    unittest.main()
