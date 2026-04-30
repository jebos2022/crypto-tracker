import unittest

from core.models import GAS_FEE, TRANSFER_OUT
from core.parsers import _parse_txlist_row


class ParserMethodMetadataTests(unittest.TestCase):
    def test_txlist_rows_preserve_method_metadata(self) -> None:
        wallet = "0x" + "1" * 40
        raw = {
            "from": wallet,
            "to": "0x" + "2" * 40,
            "isError": "0",
            "hash": "0x" + "a" * 64,
            "blockNumber": "123",
            "timeStamp": "1777573655",
            "value": "1000000000000000000",
            "gasUsed": "21000",
            "gasPrice": "1000000000",
            "methodId": "0x095ea7b3",
            "functionName": "approve(address spender,uint256 amount)",
        }

        rows = _parse_txlist_row(raw, wallet, "ethereum")

        self.assertEqual([r["type"] for r in rows], [TRANSFER_OUT, GAS_FEE])
        self.assertTrue(all(r["method_id"] == "0x095ea7b3" for r in rows))
        self.assertTrue(all(r["method_name"] == "approve(address spender,uint256 amount)" for r in rows))
        self.assertTrue(all(r["from_address"] == wallet for r in rows))
        self.assertTrue(all(r["to_address"] == "0x" + "2" * 40 for r in rows))


if __name__ == "__main__":
    unittest.main()
