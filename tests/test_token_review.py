import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import db, fetcher, token_review


SAFE_USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
FAKE_USDC = "0x" + "9" * 40


class TokenReviewClassifierTests(unittest.TestCase):
    def test_classifier_flags_regex_scam(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "claim rewards at scam.example.com",
            "contract_address": FAKE_USDC,
        })

        self.assertEqual(result.status, token_review.STATUS_SCAM)
        self.assertFalse(result.accepted_by_default)

    def test_classifier_flags_suspicious_metadata(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "ODD",
            "contract_address": FAKE_USDC,
            "has_metadata": 1,
            "verified": 0,
            "has_website": 0,
            "has_social": 0,
        })

        self.assertEqual(result.status, token_review.STATUS_SUSPICIOUS)
        self.assertFalse(result.accepted_by_default)

    def test_classifier_accepts_verified_and_known_safe(self) -> None:
        verified = token_review.classify_token({
            "chain": "ethereum",
            "asset": "REAL",
            "contract_address": FAKE_USDC,
            "has_metadata": 1,
            "verified": 1,
        })
        known = token_review.classify_token({
            "chain": "ethereum",
            "asset": "USDC",
            "contract_address": SAFE_USDC,
        })

        self.assertEqual(verified.status, token_review.STATUS_SAFE)
        self.assertTrue(verified.accepted_by_default)
        self.assertEqual(known.status, token_review.STATUS_SAFE)
        self.assertTrue(known.accepted_by_default)

    def test_classifier_keeps_clean_unproven_token_unknown(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "NEWTOKEN",
            "contract_address": FAKE_USDC,
        })

        self.assertEqual(result.status, token_review.STATUS_UNKNOWN)
        self.assertFalse(result.accepted_by_default)


class TokenReviewDatabaseTests(unittest.TestCase):
    def _path(self) -> Path:
        return Path(tempfile.mkdtemp()) / "review.db"

    def _conn_factory(self, path: Path):
        def conn_factory() -> sqlite3.Connection:
            conn = sqlite3.connect(path)
            conn.row_factory = sqlite3.Row
            return conn

        return conn_factory

    def _with_token_review_db(self, path: Path):
        conn_factory = self._conn_factory(path)
        original_token_conn = token_review.get_connection
        original_fetcher_conn = fetcher.get_connection
        token_review.get_connection = conn_factory
        fetcher.get_connection = conn_factory
        self.addCleanup(lambda: setattr(token_review, "get_connection", original_token_conn))
        self.addCleanup(lambda: setattr(fetcher, "get_connection", original_fetcher_conn))
        return conn_factory

    def test_migration_rebuilds_contract_aware_rows_and_defaults(self) -> None:
        path = self._path()
        conn_factory = self._with_token_review_db(path)
        conn = conn_factory()
        conn.executescript("""
            CREATE TABLE wallets (
                id INTEGER PRIMARY KEY,
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
                asset TEXT NOT NULL,
                contract_address TEXT,
                accepted INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (wallet_id, chain, asset)
            );
            CREATE TABLE token_metadata (
                contract_address TEXT NOT NULL,
                chain TEXT NOT NULL,
                verified INTEGER NOT NULL DEFAULT 0,
                holder_count INTEGER,
                has_website INTEGER NOT NULL DEFAULT 0,
                has_social INTEGER NOT NULL DEFAULT 0,
                fetched_at TEXT NOT NULL,
                PRIMARY KEY (contract_address, chain)
            );
        """)
        conn.executemany(
            """
            INSERT INTO transactions
                (id, wallet_id, chain, timestamp, block_number, tx_hash, type,
                 asset, contract_address, amount, source)
            VALUES (?, 1, 'ethereum', '2026-04-30T10:00:00', 1, ?, 'TRANSFER_IN',
                    'USDC', ?, '1', 'tokentx')
            """,
            [
                ("safe", "0x" + "a" * 64, SAFE_USDC),
                ("fake", "0x" + "b" * 64, FAKE_USDC),
            ],
        )
        conn.commit()

        db._migrate_token_review_contract_keys(conn)
        conn.commit()
        conn.close()

        token_review.reclassify_all_token_reviews()

        conn = conn_factory()
        rows = {
            r["token_key"]: dict(r)
            for r in conn.execute("SELECT * FROM token_review").fetchall()
        }
        conn.close()

        self.assertEqual(set(rows), {SAFE_USDC, FAKE_USDC})
        self.assertEqual(rows[SAFE_USDC]["review_status"], token_review.STATUS_SAFE)
        self.assertEqual(rows[SAFE_USDC]["accepted"], 1)
        self.assertEqual(rows[FAKE_USDC]["review_status"], token_review.STATUS_UNKNOWN)
        self.assertEqual(rows[FAKE_USDC]["accepted"], 0)

    def test_fetcher_stores_scam_transaction_but_rejects_token_review(self) -> None:
        path = self._path()
        conn_factory = self._with_token_review_db(path)
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        conn.execute("INSERT INTO wallets (id, name, address) VALUES (1, 'Main', '0xabc')")
        conn.commit()
        conn.close()

        row = {
            "id": "tx1",
            "chain": "ethereum",
            "timestamp": "2026-04-30T10:00:00",
            "block_number": 1,
            "tx_hash": "0x" + "c" * 64,
            "from_address": "0x" + "1" * 40,
            "to_address": "0x" + "2" * 40,
            "type": "TRANSFER_IN",
            "asset": "claim rewards at scam.example.com",
            "contract_address": FAKE_USDC,
            "amount": "1",
            "source": "tokentx",
            "method_id": None,
            "method_name": None,
        }
        inserted = fetcher._insert_rows([row], 1)
        fetcher._upsert_token_review(1, "ethereum", row["asset"], row["contract_address"])

        conn = conn_factory()
        tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        review = conn.execute("SELECT * FROM token_review").fetchone()
        conn.close()

        self.assertEqual(inserted, 1)
        self.assertEqual(tx_count, 1)
        self.assertEqual(review["review_status"], token_review.STATUS_SCAM)
        self.assertEqual(review["accepted"], 0)

    def test_user_override_survives_metadata_reclassification(self) -> None:
        path = self._path()
        conn_factory = self._with_token_review_db(path)
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        conn.execute("INSERT INTO wallets (id, name, address) VALUES (1, 'Main', '0xabc')")
        conn.execute(
            """
            INSERT INTO token_review
                (wallet_id, chain, token_key, asset, contract_address, accepted,
                 review_status, review_reason, decision_source)
            VALUES (1, 'ethereum', ?, 'ODD', ?, 1, 'unknown', 'Nog onvoldoende metadata', 'user')
            """,
            (FAKE_USDC, FAKE_USDC),
        )
        conn.execute(
            """
            INSERT INTO token_metadata
                (contract_address, chain, verified, holder_count, has_website, has_social, fetched_at)
            VALUES (?, 'ethereum', 0, 10, 0, 0, '2026-04-30T10:00:00')
            """,
            (FAKE_USDC,),
        )
        conn.commit()
        conn.close()

        token_review.reclassify_all_token_reviews()

        conn = conn_factory()
        row = conn.execute("SELECT * FROM token_review").fetchone()
        conn.close()

        self.assertEqual(row["review_status"], token_review.STATUS_SUSPICIOUS)
        self.assertEqual(row["accepted"], 1)
        self.assertEqual(row["decision_source"], token_review.USER_DECISION)

    def test_contract_aware_join_only_returns_accepted_contract(self) -> None:
        path = self._path()
        conn_factory = self._with_token_review_db(path)
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        conn.execute("INSERT INTO wallets (id, name, address) VALUES (1, 'Main', '0xabc')")
        for suffix, contract, accepted in (("safe", SAFE_USDC, 1), ("fake", FAKE_USDC, 0)):
            conn.execute(
                """
                INSERT INTO transactions
                    (id, wallet_id, chain, timestamp, block_number, tx_hash, type,
                     asset, contract_address, amount, source)
                VALUES (?, 1, 'ethereum', '2026-04-30T10:00:00', 1, ?, 'TRANSFER_IN',
                        'USDC', ?, '1', 'tokentx')
                """,
                (suffix, "0x" + suffix[0] * 64, contract),
            )
            conn.execute(
                """
                INSERT INTO token_review
                    (wallet_id, chain, token_key, asset, contract_address, accepted)
                VALUES (1, 'ethereum', ?, 'USDC', ?, ?)
                """,
                (contract, contract, accepted),
            )
        conn.commit()

        rows = conn.execute(
            f"""
            SELECT t.contract_address
            FROM transactions t
            JOIN token_review tr
              ON {token_review.token_review_join_condition("t", "tr")}
            WHERE tr.accepted = 1
            """
        ).fetchall()
        conn.close()

        self.assertEqual([r["contract_address"] for r in rows], [SAFE_USDC])


if __name__ == "__main__":
    unittest.main()
