from datetime import date
import unittest

from core.ledger import (
    csv_filename,
    explorer_tx_url,
    logical_tx_groups,
    method_label,
    normalize_tx_hash,
    short_tx_hash,
)


HASH = "0x" + "a" * 64


class LedgerHelperTests(unittest.TestCase):
    def test_normalize_tx_hash_strips_fetcher_suffixes(self) -> None:
        self.assertEqual(normalize_tx_hash(HASH), HASH)
        self.assertEqual(normalize_tx_hash(f"{HASH}_fee"), HASH)
        self.assertEqual(normalize_tx_hash(f"{HASH}_int_7"), HASH)
        self.assertEqual(normalize_tx_hash(f"{HASH}_dup2"), HASH)

    def test_explorer_tx_url_uses_normalized_hash(self) -> None:
        self.assertEqual(explorer_tx_url("ethereum", f"{HASH}_fee"), f"https://etherscan.io/tx/{HASH}")
        self.assertEqual(explorer_tx_url("beam", f"{HASH}_int_3"), f"https://subnets.avax.network/beam/tx/{HASH}")

    def test_short_tx_hash_uses_normalized_hash(self) -> None:
        self.assertEqual(short_tx_hash(f"{HASH}_dup1"), "0xaaaaaaaa...aaaaaa")

    def test_csv_filename_slugs_filter_context(self) -> None:
        self.assertEqual(
            csv_filename("Alle wallets", "Alle chains", "stPEAR", date(2026, 4, 30)),
            "transactions_alle-wallets_alle-chains_stpear_2026-04-30.csv",
        )

    def test_csv_filename_can_include_year_filter(self) -> None:
        self.assertEqual(
            csv_filename(
                "Main wallet",
                "Ethereum",
                "Alle tokens",
                date(2026, 4, 30),
                year_label="2022",
            ),
            "transactions_main-wallet_ethereum_alle-tokens_2022_2026-04-30.csv",
        )

    def test_logical_tx_groups_keeps_one_on_chain_transaction_together(self) -> None:
        rows = [
            _row(f"{HASH}_fee", "GAS_FEE", "ETH", "-0.003", "txlist"),
            _row(HASH, "TRANSFER_OUT", "ETH", "-1", "txlist"),
            _row(f"{HASH}_dup1", "TRANSFER_IN", "GET", "1", "tokentx"),
        ]

        groups = logical_tx_groups(rows)

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["tx_hash"], HASH)
        self.assertEqual(groups[0]["type"], "SWAP")
        self.assertEqual(groups[0]["row_count"], 3)
        self.assertEqual(groups[0]["assets"], ["ETH", "GET"])
        self.assertEqual(groups[0]["sources"], ["tokentx", "txlist"])

    def test_logical_tx_groups_asset_filter_keeps_context_rows(self) -> None:
        rows = [
            _row(f"{HASH}_fee", "GAS_FEE", "ETH", "-0.003", "txlist"),
            _row(HASH, "TRANSFER_OUT", "ETH", "-1", "txlist"),
            _row(f"{HASH}_dup1", "TRANSFER_IN", "GET", "1", "tokentx"),
        ]

        groups = logical_tx_groups(rows, asset_filter="GET")

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["row_count"], 3)

    def test_logical_tx_groups_can_hide_gas_only_transactions(self) -> None:
        groups = logical_tx_groups(
            [_row(f"{HASH}_fee", "GAS_FEE", "ETH", "-0.003", "txlist")],
            include_gas_only=False,
        )

        self.assertEqual(groups, [])

    def test_method_label_humanizes_function_name(self) -> None:
        self.assertEqual(method_label("approve(address spender,uint256 amount)", "0x095ea7b3"), "Approve")
        self.assertEqual(method_label("swapExactETHForTokens(uint256,address[],address,uint256)"), "Swap Exact ETH For Tokens")
        self.assertEqual(method_label("", "0x12345678"), "0x12345678")


def _row(tx_hash: str, tx_type: str, asset: str, amount: str, source: str) -> dict:
    return {
        "wallet": "Main",
        "chain": "ethereum",
        "timestamp": "2026-04-30T10:00:00",
        "block_number": 123,
        "tx_hash": tx_hash,
        "from_address": "0x" + "1" * 40,
        "to_address": "0x" + "2" * 40,
        "type": tx_type,
        "asset": asset,
        "amount": amount,
        "source": source,
        "method_id": None,
        "method_name": None,
    }


if __name__ == "__main__":
    unittest.main()
