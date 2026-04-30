import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import ledger_backfill


HASH = "0x" + "b" * 64


class LedgerBackfillTests(unittest.TestCase):
    def test_update_matching_rows_handles_suffixed_tx_hashes(self) -> None:
        path = Path(tempfile.mkdtemp()) / "backfill.db"

        def conn_factory() -> sqlite3.Connection:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn

        conn = conn_factory()
        conn.execute(
            """
            CREATE TABLE transactions (
                wallet_id INTEGER,
                chain TEXT,
                tx_hash TEXT,
                source TEXT,
                method_id TEXT,
                method_name TEXT,
                from_address TEXT,
                to_address TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (1, "ethereum", HASH, "txlist", None, None, None, None),
                (1, "ethereum", f"{HASH}_fee", "txlist", None, None, None, None),
                (1, "ethereum", HASH, "tokentx", None, None, None, None),
            ],
        )
        conn.commit()
        conn.close()

        original = ledger_backfill.get_connection
        ledger_backfill.get_connection = conn_factory
        try:
            updated = ledger_backfill._update_matching_rows(
                1,
                "ethereum",
                HASH,
                "0x095ea7b3",
                "approve(address spender,uint256 amount)",
                "0x" + "1" * 40,
                "0x" + "2" * 40,
            )
        finally:
            ledger_backfill.get_connection = original

        conn = conn_factory()
        rows = {
            (r["tx_hash"], r["source"]): (r["method_name"], r["from_address"], r["to_address"])
            for r in conn.execute("SELECT tx_hash, source, method_name, from_address, to_address FROM transactions").fetchall()
        }
        conn.close()

        self.assertEqual(updated, 2)
        self.assertEqual(rows[(HASH, "txlist")][0], "approve(address spender,uint256 amount)")
        self.assertEqual(rows[(HASH, "txlist")][1], "0x" + "1" * 40)
        self.assertEqual(rows[(HASH, "txlist")][2], "0x" + "2" * 40)
        self.assertEqual(rows[(f"{HASH}_fee", "txlist")][0], "approve(address spender,uint256 amount)")
        self.assertEqual(rows[(HASH, "tokentx")][0], None)

    def test_update_matching_rows_does_not_recount_missing_method_name_without_new_value(self) -> None:
        path = Path(tempfile.mkdtemp()) / "backfill.db"

        def conn_factory() -> sqlite3.Connection:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn

        conn = conn_factory()
        conn.execute(
            """
            CREATE TABLE transactions (
                wallet_id INTEGER,
                chain TEXT,
                tx_hash TEXT,
                source TEXT,
                method_id TEXT,
                method_name TEXT,
                from_address TEXT,
                to_address TEXT
            )
            """
        )
        conn.execute(
            "INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                "ethereum",
                HASH,
                "txlist",
                "0x2213bc0b",
                None,
                "0x" + "1" * 40,
                "0x" + "2" * 40,
            ),
        )
        conn.commit()
        conn.close()

        original = ledger_backfill.get_connection
        ledger_backfill.get_connection = conn_factory
        try:
            updated = ledger_backfill._update_matching_rows(
                1,
                "ethereum",
                HASH,
                "0x2213bc0b",
                None,
                "0x" + "1" * 40,
                "0x" + "2" * 40,
            )
        finally:
            ledger_backfill.get_connection = original

        self.assertEqual(updated, 0)


if __name__ == "__main__":
    unittest.main()
