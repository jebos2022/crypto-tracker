import unittest

from core.models import TRANSFER_IN, WETH_CONTRACTS
from core.wrap_reconcile import synthesize_wrap_rows


HASH = "0x" + "a" * 64
WALLET = "0x" + "1" * 40
WETH = WETH_CONTRACTS["ethereum"]


class WrapReconcileTests(unittest.TestCase):
    def _raw_wrap(self, **overrides) -> dict:
        raw = {
            "from": WALLET,
            "to": WETH,
            "isError": "0",
            "hash": HASH,
            "blockNumber": "123",
            "timeStamp": "1777573655",
            "value": "1000000000000000000",
        }
        raw.update(overrides)
        return raw

    def test_synthesizes_missing_weth_inflow_from_txlist_value(self) -> None:
        rows = synthesize_wrap_rows([], [self._raw_wrap()], "ethereum")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], TRANSFER_IN)
        self.assertEqual(rows[0]["asset"], "WETH")
        self.assertEqual(rows[0]["contract_address"], WETH)
        self.assertEqual(rows[0]["amount"], "1")
        self.assertEqual(rows[0]["block_number"], 123)

    def test_invalid_txlist_value_raises_instead_of_zeroing(self) -> None:
        with self.assertRaisesRegex(ValueError, "txlist.value"):
            synthesize_wrap_rows([], [self._raw_wrap(value="not-a-number")], "ethereum")

    def test_invalid_block_number_raises_with_context(self) -> None:
        with self.assertRaisesRegex(ValueError, "blockNumber"):
            synthesize_wrap_rows([], [self._raw_wrap(blockNumber="latest")], "ethereum")


if __name__ == "__main__":
    unittest.main()
