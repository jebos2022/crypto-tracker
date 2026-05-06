import sqlite3
import tempfile
import unittest
from pathlib import Path

from core import db, fetcher, token_review


HASH = "0x" + "a" * 64
WALLET_1 = "0x" + "1" * 40
WALLET_2 = "0x" + "2" * 40
OTHER = "0x" + "9" * 40
TOKEN = "0x" + "3" * 40
SAFE_USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
PEAR = "0x3212dc0f8c834e4de893532d27cc9b6001684db0"
STPEAR = "0xce3be5204017bb1bd279937f92df09fd7f539b92"


class FetcherDedupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = Path(tempfile.mkdtemp()) / "fetcher.db"

        def conn_factory() -> sqlite3.Connection:
            conn = sqlite3.connect(self.path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            return conn

        self.conn_factory = conn_factory
        conn = conn_factory()
        conn.executescript(db.SCHEMA_SQL)
        conn.executescript(db.INDICES_SQL)
        conn.executemany(
            "INSERT INTO wallets (id, name, address) VALUES (?, ?, ?)",
            [(1, "main", WALLET_1), (2, "cold", WALLET_2)],
        )
        conn.commit()
        conn.close()

        self.original_get_connection = fetcher.get_connection
        self.original_fetch_tokentx = fetcher.api.fetch_tokentx
        self.original_fetch_txlist = fetcher.api.fetch_txlist
        self.original_fetch_txlistinternal = fetcher.api.fetch_txlistinternal
        self.original_synthesize_wrap_rows = fetcher.synthesize_wrap_rows
        fetcher.get_connection = conn_factory

    def tearDown(self) -> None:
        fetcher.get_connection = self.original_get_connection
        fetcher.api.fetch_tokentx = self.original_fetch_tokentx
        fetcher.api.fetch_txlist = self.original_fetch_txlist
        fetcher.api.fetch_txlistinternal = self.original_fetch_txlistinternal
        fetcher.synthesize_wrap_rows = self.original_synthesize_wrap_rows

    def _mock_api(self, tokentx=None, txlist=None, internal=None) -> None:
        fetcher.api.fetch_tokentx = lambda _addr, _chain, _startblock: list(tokentx or [])
        fetcher.api.fetch_txlist = lambda _addr, _chain, _startblock: list(txlist or [])
        fetcher.api.fetch_txlistinternal = lambda _addr, _chain, _startblock: list(internal or [])

    def _rows(self) -> list[sqlite3.Row]:
        conn = self.conn_factory()
        rows = conn.execute(
            "SELECT wallet_id, tx_hash, source, asset, amount FROM transactions "
            "ORDER BY wallet_id, source, tx_hash"
        ).fetchall()
        conn.close()
        return rows

    def _last_block_rows(self) -> list[sqlite3.Row]:
        conn = self.conn_factory()
        rows = conn.execute(
            "SELECT chain, endpoint, last_block FROM wallet_chain_state "
            "ORDER BY chain, endpoint"
        ).fetchall()
        conn.close()
        return rows

    def _review_rows(self) -> list[sqlite3.Row]:
        conn = self.conn_factory()
        rows = conn.execute(
            "SELECT chain, token_key, asset, accepted, decision_source, review_status "
            "FROM token_review ORDER BY chain, token_key"
        ).fetchall()
        conn.close()
        return rows

    def test_same_hash_from_tokentx_and_txlist_is_kept_per_source(self) -> None:
        self._mock_api(
            tokentx=[
                {
                    "from": OTHER,
                    "to": WALLET_1,
                    "hash": HASH,
                    "blockNumber": "10",
                    "timeStamp": "1777573655",
                    "value": "2500000",
                    "tokenDecimal": "6",
                    "tokenSymbol": "TST",
                    "contractAddress": TOKEN,
                }
            ],
            txlist=[
                {
                    "from": WALLET_1,
                    "to": OTHER,
                    "isError": "0",
                    "hash": HASH,
                    "blockNumber": "10",
                    "timeStamp": "1777573655",
                    "value": "1000000000000000000",
                    "gasUsed": "21000",
                    "gasPrice": "1000000000",
                }
            ],
        )

        result = fetcher.fetch_wallet(1, WALLET_1, "ethereum")
        rows = self._rows()

        self.assertEqual(result.new_tx, 3)
        self.assertIn((HASH, "tokentx"), {(r["tx_hash"], r["source"]) for r in rows})
        self.assertIn((HASH, "txlist"), {(r["tx_hash"], r["source"]) for r in rows})
        self.assertIn((f"{HASH}_fee", "txlist"), {(r["tx_hash"], r["source"]) for r in rows})

    def test_same_hash_same_source_is_kept_for_different_wallets(self) -> None:
        self._mock_api(
            txlist=[
                {
                    "from": WALLET_1,
                    "to": OTHER,
                    "isError": "0",
                    "hash": HASH,
                    "blockNumber": "10",
                    "timeStamp": "1777573655",
                    "value": "1000000000000000000",
                    "gasUsed": "21000",
                    "gasPrice": "1000000000",
                }
            ],
        )
        fetcher.fetch_wallet(1, WALLET_1, "ethereum")

        self._mock_api(
            txlist=[
                {
                    "from": OTHER,
                    "to": WALLET_2,
                    "isError": "0",
                    "hash": HASH,
                    "blockNumber": "10",
                    "timeStamp": "1777573655",
                    "value": "1000000000000000000",
                    "gasUsed": "21000",
                    "gasPrice": "1000000000",
                }
            ],
        )
        result = fetcher.fetch_wallet(2, WALLET_2, "ethereum")
        rows = self._rows()

        self.assertEqual(result.new_tx, 1)
        self.assertEqual(
            [(r["wallet_id"], r["tx_hash"], r["source"]) for r in rows if r["tx_hash"] == HASH],
            [(1, HASH, "txlist"), (2, HASH, "txlist")],
        )

    def test_duplicate_tokentx_hashes_get_stable_suffixes(self) -> None:
        self._mock_api(
            tokentx=[
                {
                    "from": OTHER,
                    "to": WALLET_1,
                    "hash": HASH,
                    "blockNumber": "10",
                    "timeStamp": "1777573655",
                    "value": "1000000",
                    "tokenDecimal": "6",
                    "tokenSymbol": "TST",
                    "contractAddress": TOKEN,
                },
                {
                    "from": OTHER,
                    "to": WALLET_1,
                    "hash": HASH,
                    "blockNumber": "10",
                    "timeStamp": "1777573655",
                    "value": "2000000",
                    "tokenDecimal": "6",
                    "tokenSymbol": "TST",
                    "contractAddress": TOKEN,
                },
            ],
        )

        result = fetcher.fetch_wallet(1, WALLET_1, "ethereum")
        hashes = [r["tx_hash"] for r in self._rows()]

        self.assertEqual(result.new_tx, 2)
        self.assertEqual(hashes, [HASH, f"{HASH}_dup1"])

    def test_txlist_parse_error_does_not_advance_txlist_cursor(self) -> None:
        self._mock_api(
            txlist=[
                {
                    "from": WALLET_1,
                    "to": OTHER,
                    "isError": "0",
                    "hash": HASH,
                    "blockNumber": "10",
                    "timeStamp": "1777573655",
                    "value": "1000000000000000000",
                    "gasUsed": "21000",
                    "gasPrice": "1000000000",
                },
                {
                    "from": WALLET_1,
                    "to": OTHER,
                    "isError": "0",
                    "hash": "0x" + "b" * 64,
                    "blockNumber": "11",
                    "timeStamp": "1777573655",
                    "value": "bad-value",
                    "gasUsed": "21000",
                    "gasPrice": "1000000000",
                },
            ],
        )

        result = fetcher.fetch_wallet(1, WALLET_1, "ethereum")

        self.assertEqual(result.new_tx, 2)
        self.assertIn("txlist", result.endpoint_errors)
        self.assertEqual(
            [(r["endpoint"], r["last_block"]) for r in self._last_block_rows()],
            [],
        )

    def test_wrap_reconcile_error_does_not_advance_txlist_cursor(self) -> None:
        self._mock_api(
            txlist=[
                {
                    "from": WALLET_1,
                    "to": OTHER,
                    "isError": "0",
                    "hash": HASH,
                    "blockNumber": "10",
                    "timeStamp": "1777573655",
                    "value": "1000000000000000000",
                    "gasUsed": "21000",
                    "gasPrice": "1000000000",
                }
            ],
        )

        def raise_wrap_error(_buffer, _txlist_rows, _chain):
            raise ValueError("synthetic wrap failed")

        fetcher.synthesize_wrap_rows = raise_wrap_error

        result = fetcher.fetch_wallet(1, WALLET_1, "ethereum")

        self.assertEqual(result.new_tx, 2)
        self.assertIn("txlist", result.endpoint_errors)
        self.assertEqual(
            [(r["endpoint"], r["last_block"]) for r in self._last_block_rows()],
            [],
        )

    def test_insert_rows_counts_only_new_rows(self) -> None:
        row = {
            "id": "tx1",
            "chain": "ethereum",
            "timestamp": "2026-01-01T00:00:00",
            "block_number": 1,
            "tx_hash": HASH,
            "from_address": WALLET_1,
            "to_address": OTHER,
            "type": "TRANSFER_OUT",
            "asset": "ETH",
            "contract_address": None,
            "amount": "-1",
            "source": "txlist",
            "method_id": None,
            "method_name": None,
        }

        inserted = fetcher._insert_rows([row, {**row, "id": "tx1-dupe"}], 1)
        inserted_again = fetcher._insert_rows([{**row, "id": "tx1-again"}], 1)

        self.assertEqual(inserted, 1)
        self.assertEqual(inserted_again, 0)

    def test_bulk_token_review_dedups_rows_and_preserves_user_override(self) -> None:
        conn = self.conn_factory()
        conn.execute(
            """
            INSERT INTO token_review
                (wallet_id, chain, token_key, asset, contract_address, accepted,
                 decision_source)
            VALUES (1, 'ethereum', ?, 'USDC', ?, 0, ?)
            """,
            (SAFE_USDC, SAFE_USDC, token_review.USER_DECISION),
        )
        conn.commit()
        conn.close()

        rows = [
            {"chain": "ethereum", "asset": "USDC", "contract_address": SAFE_USDC},
            {"chain": "ethereum", "asset": "USDC", "contract_address": SAFE_USDC},
        ]

        fetcher._upsert_token_reviews(1, rows)
        review_rows = self._review_rows()

        self.assertEqual(len(review_rows), 1)
        self.assertEqual(review_rows[0]["accepted"], 0)
        self.assertEqual(review_rows[0]["decision_source"], token_review.USER_DECISION)
        self.assertEqual(review_rows[0]["review_status"], token_review.STATUS_SAFE)

    def test_bulk_token_review_accepts_staking_wrapper_when_underlying_is_in_same_batch(self) -> None:
        fetcher._upsert_token_reviews(1, [
            {"chain": "arbitrum", "asset": "stPEAR", "contract_address": STPEAR},
            {"chain": "arbitrum", "asset": "PEAR", "contract_address": PEAR},
        ])

        rows = {row["asset"]: row for row in self._review_rows()}

        self.assertEqual(rows["PEAR"]["accepted"], 1)
        self.assertEqual(rows["stPEAR"]["accepted"], 1)
        self.assertEqual(rows["stPEAR"]["decision_source"], token_review.AUTO_DECISION)


if __name__ == "__main__":
    unittest.main()
