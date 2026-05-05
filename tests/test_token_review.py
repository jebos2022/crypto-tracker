import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import db, fetcher, token_review
from core.ledger import explorer_address_url
from core.token_identity import ARB_ARBITRUM_CONTRACT


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

    def test_classifier_accepts_public_contract_evidence(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "GET",
            "contract_address": "0x8a854288a5976036a725879164ca3e91d30c6a1b",
            "public_evidence": [{
                "source": token_review.SOURCE_COINGECKO_LIST,
                "status": token_review.STATUS_SAFE,
                "reason": "CoinGecko token list",
            }],
        })

        self.assertEqual(result.status, token_review.STATUS_SAFE)
        self.assertEqual(result.reason, "CoinGecko token list")
        self.assertTrue(result.accepted_by_default)

    def test_classifier_accepts_coinmarketcap_contract_evidence(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "BICO",
            "contract_address": "0xf17e65822b568b3903685a7c9f496cf7656cc6c2",
            "public_evidence": [{
                "source": token_review.SOURCE_COINMARKETCAP_CONTRACT,
                "status": token_review.STATUS_SAFE,
                "reason": "CoinMarketCap contract metadata",
            }],
        })

        self.assertEqual(result.status, token_review.STATUS_SAFE)
        self.assertEqual(result.reason, "CoinMarketCap contract metadata")
        self.assertTrue(result.accepted_by_default)

    def test_classifier_keeps_fake_same_symbol_unknown_without_public_evidence(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "GET",
            "contract_address": FAKE_USDC,
        })

        self.assertEqual(result.status, token_review.STATUS_UNKNOWN)
        self.assertFalse(result.accepted_by_default)

    def test_classifier_flags_known_ticker_wrong_contract(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "USDC",
            "contract_address": FAKE_USDC,
            "public_evidence": [{
                "source": token_review.SOURCE_COINGECKO_LIST,
                "status": token_review.STATUS_SAFE,
                "reason": "CoinGecko token list",
            }],
        })

        self.assertEqual(result.status, token_review.STATUS_SUSPICIOUS)
        self.assertIn("Ticker lijkt op USDC", result.reason)
        self.assertFalse(result.accepted_by_default)

    def test_classifier_accepts_known_arb_contract(self) -> None:
        result = token_review.classify_token({
            "chain": "arbitrum",
            "asset": "ARB",
            "contract_address": ARB_ARBITRUM_CONTRACT,
        })

        self.assertEqual(result.status, token_review.STATUS_SAFE)
        self.assertTrue(result.accepted_by_default)

    def test_classifier_flags_fake_arb_even_with_public_evidence(self) -> None:
        result = token_review.classify_token({
            "chain": "arbitrum",
            "asset": "ARB",
            "contract_address": FAKE_USDC,
            "public_evidence": [{
                "source": token_review.SOURCE_COINGECKO_LIST,
                "status": token_review.STATUS_SAFE,
                "reason": "CoinGecko token list",
            }],
        })

        self.assertEqual(result.status, token_review.STATUS_SUSPICIOUS)
        self.assertIn("Ticker lijkt op ARB", result.reason)
        self.assertFalse(result.accepted_by_default)

    def test_classifier_flags_fake_staking_wrapper_contract(self) -> None:
        result = token_review.classify_token({
            "chain": "arbitrum",
            "asset": "stPEAR",
            "contract_address": FAKE_USDC,
        })

        self.assertEqual(result.status, token_review.STATUS_SUSPICIOUS)
        self.assertFalse(result.accepted_by_default)

    def test_classifier_rejects_goplus_high_risk_even_if_public_known(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "KNOWN",
            "contract_address": FAKE_USDC,
            "public_evidence": [
                {
                    "source": token_review.SOURCE_COINGECKO_LIST,
                    "status": token_review.STATUS_SAFE,
                    "reason": "CoinGecko token list",
                },
                {
                    "source": token_review.SOURCE_GOPLUS,
                    "status": token_review.STATUS_SCAM,
                    "reason": "GoPlus high-risk: is_honeypot",
                },
            ],
        })

        self.assertEqual(result.status, token_review.STATUS_SCAM)
        self.assertFalse(result.accepted_by_default)

    def test_classifier_does_not_auto_accept_only_goplus_safe(self) -> None:
        result = token_review.classify_token({
            "chain": "ethereum",
            "asset": "UNLISTED",
            "contract_address": FAKE_USDC,
            "public_evidence": [{
                "source": token_review.SOURCE_GOPLUS,
                "status": token_review.STATUS_SAFE,
                "reason": "GoPlus geen high-risk flags",
            }],
        })

        self.assertEqual(result.status, token_review.STATUS_UNKNOWN)
        self.assertFalse(result.accepted_by_default)

    def test_explorer_address_url_points_to_contract_page(self) -> None:
        self.assertEqual(
            explorer_address_url("ethereum", SAFE_USDC),
            f"https://etherscan.io/address/{SAFE_USDC}",
        )

    def test_extract_cmc_match_requires_exact_contract(self) -> None:
        payload = {
            "123": {
                "name": "Biconomy",
                "symbol": "BICO",
                "platform": {
                    "name": "Ethereum",
                    "slug": "ethereum",
                    "token_address": "0xf17e65822b568b3903685a7c9f496cf7656cc6c2",
                },
            }
        }

        match = token_review._extract_cmc_match(
            payload,
            "ethereum",
            "0xf17e65822b568b3903685a7c9f496cf7656cc6c2",
        )
        miss = token_review._extract_cmc_match(payload, "ethereum", FAKE_USDC)

        self.assertEqual(match["symbol"], "BICO")
        self.assertIsNone(miss)


class TokenIntakeGuidanceTests(unittest.TestCase):
    def test_guidance_hides_clear_scam(self) -> None:
        guidance = token_review.token_intake_guidance({
            "review_status": token_review.STATUS_SCAM,
            "review_reason": "Scam-naam bevat URL/claim of verdacht patroon",
            "tx_count": 1,
            "in_count": 1,
            "out_count": 0,
        })

        self.assertEqual(guidance.bucket, token_review.INTAKE_HIDDEN)
        self.assertEqual(guidance.action, "Verborgen laten")

    def test_guidance_moves_unknown_airdrop_to_noise(self) -> None:
        guidance = token_review.token_intake_guidance({
            "review_status": token_review.STATUS_UNKNOWN,
            "review_reason": "Geen publieke bronmatch",
            "tx_count": 1,
            "in_count": 1,
            "out_count": 0,
            "net_amount": 1000,
        })

        self.assertEqual(guidance.bucket, token_review.INTAKE_NOISE)
        self.assertIn("airdrop", guidance.why)

    def test_guidance_keeps_self_initiated_swap_out_of_noise(self) -> None:
        guidance = token_review.token_intake_guidance({
            "review_status": token_review.STATUS_UNKNOWN,
            "review_reason": "Geen publieke bronmatch",
            "tx_count": 1,
            "in_count": 1,
            "out_count": 0,
            "net_amount": 1000,
            "self_initiated_swap_count": 1,
        })

        self.assertEqual(guidance.bucket, token_review.INTAKE_REVIEW)
        self.assertEqual(guidance.action, "Waarschijnlijk importeren")

    def test_guidance_hides_bulk_airdrop(self) -> None:
        guidance = token_review.token_intake_guidance({
            "review_status": token_review.STATUS_UNKNOWN,
            "review_reason": "Geen publieke bronmatch",
            "tx_count": 1,
            "in_count": 1,
            "out_count": 0,
            "bulk_airdrop_count": 1,
        })

        self.assertEqual(guidance.bucket, token_review.INTAKE_HIDDEN)
        self.assertEqual(guidance.action, "Waarschijnlijk phishing-airdrop")

    def test_guidance_keeps_unknown_with_own_activity_in_review(self) -> None:
        guidance = token_review.token_intake_guidance({
            "review_status": token_review.STATUS_UNKNOWN,
            "review_reason": "Geen publieke bronmatch",
            "tx_count": 2,
            "in_count": 1,
            "out_count": 1,
            "net_amount": 0.5,
        })

        self.assertEqual(guidance.bucket, token_review.INTAKE_REVIEW)
        self.assertEqual(guidance.action, "Handmatig controleren")

    def test_guidance_imports_safe_tokens(self) -> None:
        guidance = token_review.token_intake_guidance({
            "review_status": token_review.STATUS_SAFE,
            "review_reason": "CoinGecko token list",
            "tx_count": 3,
            "in_count": 2,
            "out_count": 1,
        })

        self.assertEqual(guidance.bucket, token_review.INTAKE_IMPORT)
        self.assertEqual(guidance.action, "Aangevinkt laten")

    def test_guidance_moves_user_accepted_unknown_to_import(self) -> None:
        guidance = token_review.token_intake_guidance({
            "review_status": token_review.STATUS_UNKNOWN,
            "review_reason": "Geen publieke bronmatch",
            "accepted": 1,
            "decision_source": token_review.USER_DECISION,
            "tx_count": 1,
            "in_count": 1,
            "out_count": 0,
        })

        self.assertEqual(guidance.bucket, token_review.INTAKE_IMPORT)
        self.assertEqual(guidance.action, "Handmatig geaccepteerd")

    def test_guidance_moves_user_rejected_token_to_hidden(self) -> None:
        guidance = token_review.token_intake_guidance({
            "review_status": token_review.STATUS_SAFE,
            "review_reason": "CoinGecko token list",
            "accepted": 0,
            "decision_source": token_review.USER_DECISION,
            "tx_count": 2,
            "in_count": 1,
            "out_count": 1,
        })

        self.assertEqual(guidance.bucket, token_review.INTAKE_HIDDEN)
        self.assertEqual(guidance.action, "Handmatig afgewezen")


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
        self.assertEqual(rows[FAKE_USDC]["review_status"], token_review.STATUS_SUSPICIOUS)
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

    def test_public_evidence_reclassification_auto_accepts_known_contract(self) -> None:
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
            VALUES (1, 'ethereum', ?, 'GET', ?, 0, 'unknown', 'Geen publieke bronmatch', 'auto')
            """,
            (FAKE_USDC, FAKE_USDC),
        )
        conn.execute(
            """
            INSERT INTO token_public_evidence
                (chain, contract_address, source, status, name, symbol, reason, payload_json, fetched_at)
            VALUES ('ethereum', ?, ?, 'safe', 'GET Protocol', 'GET', 'CoinGecko token list', '{}', '2026-04-30T10:00:00')
            """,
            (FAKE_USDC, token_review.SOURCE_COINGECKO_LIST),
        )
        conn.commit()
        conn.close()

        token_review.reclassify_all_token_reviews()

        conn = conn_factory()
        row = conn.execute("SELECT * FROM token_review").fetchone()
        conn.close()

        self.assertEqual(row["review_status"], token_review.STATUS_SAFE)
        self.assertEqual(row["review_reason"], "CoinGecko token list")
        self.assertEqual(row["accepted"], 1)

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

    def test_unique_tokens_include_contract_aware_activity_summary(self) -> None:
        path = self._path()
        conn_factory = self._with_token_review_db(path)
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        conn.execute("INSERT INTO wallets (id, name, address) VALUES (1, 'Main', '0xabc')")
        for suffix, contract, amount in (
            ("safe", SAFE_USDC, "1"),
            ("safe_out", SAFE_USDC, "-0.25"),
            ("fake", FAKE_USDC, "999"),
        ):
            conn.execute(
                """
                INSERT INTO transactions
                    (id, wallet_id, chain, timestamp, block_number, tx_hash, type,
                     asset, contract_address, amount, source)
                VALUES (?, 1, 'ethereum', '2026-04-30T10:00:00', 1, ?, 'TRANSFER_IN',
                        'USDC', ?, ?, 'tokentx')
                """,
                (suffix, "0x" + suffix[:1] * 63 + str(len(suffix) % 10), contract, amount),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO token_review
                    (wallet_id, chain, token_key, asset, contract_address, accepted)
                VALUES (1, 'ethereum', ?, 'USDC', ?, 0)
                """,
                (contract, contract),
            )
        conn.commit()
        conn.close()

        rows = {
            r["token_key"]: r
            for r in token_review.get_unique_tokens()
        }

        self.assertEqual(rows[SAFE_USDC]["tx_count"], 2)
        self.assertEqual(rows[SAFE_USDC]["in_count"], 1)
        self.assertEqual(rows[SAFE_USDC]["out_count"], 1)
        self.assertEqual(rows[FAKE_USDC]["tx_count"], 1)
        self.assertEqual(rows[FAKE_USDC]["in_count"], 1)
        self.assertEqual(rows[FAKE_USDC]["out_count"], 0)

    def test_unique_tokens_detect_self_initiated_dex_swap(self) -> None:
        path = self._path()
        conn_factory = self._with_token_review_db(path)
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        wallet = "0x" + "1" * 40
        router = "0x66a9893cc07d91d95644aedd05d03f95e1dba8af"
        token_contract = "0x" + "8" * 40
        tx_hash = "0x" + "d" * 64
        conn.execute("INSERT INTO wallets (id, name, address) VALUES (1, 'Main', ?)", (wallet,))
        conn.execute(
            """
            INSERT INTO transactions
                (id, wallet_id, chain, timestamp, block_number, tx_hash, from_address,
                 to_address, type, asset, contract_address, amount, source, method_name)
            VALUES ('swap-call', 1, 'ethereum', '2026-04-30T10:00:00', 1, ?, ?,
                    ?, 'TRANSFER_OUT', 'ETH', NULL, '-0.1', 'txlist',
                    'execute(bytes commands,bytes[] inputs,uint256 deadline)')
            """,
            (tx_hash, wallet, router),
        )
        conn.execute(
            """
            INSERT INTO transactions
                (id, wallet_id, chain, timestamp, block_number, tx_hash, from_address,
                 to_address, type, asset, contract_address, amount, source)
            VALUES ('token-in', 1, 'ethereum', '2026-04-30T10:00:00', 1, ?, ?,
                    ?, 'TRANSFER_IN', 'RARE', ?, '100', 'tokentx')
            """,
            (tx_hash, router, wallet, token_contract),
        )
        conn.execute(
            """
            INSERT INTO token_review
                (wallet_id, chain, token_key, asset, contract_address, accepted,
                 review_status, review_reason)
            VALUES (1, 'ethereum', ?, 'RARE', ?, 0, 'unknown', 'Geen publieke bronmatch')
            """,
            (token_contract, token_contract),
        )
        conn.commit()
        conn.close()

        row = token_review.get_unique_tokens()[0]
        guidance = token_review.token_intake_guidance(row)

        self.assertEqual(row["self_initiated_swap_count"], 1)
        self.assertEqual(guidance.bucket, token_review.INTAKE_REVIEW)
        self.assertEqual(guidance.action, "Waarschijnlijk importeren")

    def test_unique_tokens_detect_bulk_airdrop_method(self) -> None:
        path = self._path()
        conn_factory = self._with_token_review_db(path)
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        wallet = "0x" + "1" * 40
        sender = "0x" + "2" * 40
        token_contract = "0x" + "3" * 40
        tx_hash = "0x" + "e" * 64
        conn.execute("INSERT INTO wallets (id, name, address) VALUES (1, 'Main', ?)", (wallet,))
        conn.execute(
            """
            INSERT INTO transactions
                (id, wallet_id, chain, timestamp, block_number, tx_hash, from_address,
                 to_address, type, asset, contract_address, amount, source, method_name)
            VALUES ('bulk-in', 1, 'ethereum', '2026-04-30T10:00:00', 1, ?, ?,
                    ?, 'TRANSFER_IN', 'ETHf', ?, '3038735.093', 'tokentx',
                    'transfer(address[] dsts, uint256 value)')
            """,
            (tx_hash, sender, wallet, token_contract),
        )
        conn.execute(
            """
            INSERT INTO token_review
                (wallet_id, chain, token_key, asset, contract_address, accepted,
                 review_status, review_reason)
            VALUES (1, 'ethereum', ?, 'ETHf', ?, 0, 'unknown', 'Geen publieke bronmatch')
            """,
            (token_contract, token_contract),
        )
        conn.commit()
        conn.close()

        row = token_review.get_unique_tokens()[0]
        guidance = token_review.token_intake_guidance(row)

        self.assertEqual(row["bulk_airdrop_count"], 1)
        self.assertEqual(guidance.bucket, token_review.INTAKE_HIDDEN)
        self.assertEqual(guidance.action, "Waarschijnlijk phishing-airdrop")


if __name__ == "__main__":
    unittest.main()
