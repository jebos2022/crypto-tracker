import unittest

from core.models import GAS_FEE, TRANSFER_OUT
from core.parsers import _parse_internal_row, _parse_tokentx_row, _parse_txlist_row


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

    def test_txlist_invalid_value_raises_instead_of_zeroing(self) -> None:
        wallet = "0x" + "1" * 40
        raw = {
            "from": wallet,
            "to": "0x" + "2" * 40,
            "isError": "0",
            "hash": "0x" + "a" * 64,
            "blockNumber": "123",
            "timeStamp": "1777573655",
            "value": "not-a-number",
            "gasUsed": "21000",
            "gasPrice": "1000000000",
        }

        with self.assertRaisesRegex(ValueError, "txlist.value"):
            _parse_txlist_row(raw, wallet, "ethereum")

    def test_txlist_invalid_gas_raises_instead_of_zeroing_fee(self) -> None:
        wallet = "0x" + "1" * 40
        raw = {
            "from": wallet,
            "to": "0x" + "2" * 40,
            "isError": "1",
            "hash": "0x" + "a" * 64,
            "blockNumber": "123",
            "timeStamp": "1777573655",
            "value": "0",
            "gasUsed": "bad-gas",
            "gasPrice": "1000000000",
        }

        with self.assertRaisesRegex(ValueError, "txlist.gasUsed"):
            _parse_txlist_row(raw, wallet, "ethereum")

    def test_tokentx_invalid_amount_raises_instead_of_dropping_row(self) -> None:
        wallet = "0x" + "1" * 40
        raw = {
            "from": "0x" + "2" * 40,
            "to": wallet,
            "hash": "0x" + "a" * 64,
            "blockNumber": "123",
            "timeStamp": "1777573655",
            "value": "",
            "tokenDecimal": "18",
            "tokenSymbol": "TST",
            "contractAddress": "0x" + "3" * 40,
        }

        with self.assertRaisesRegex(ValueError, "tokentx.value"):
            _parse_tokentx_row(raw, wallet, "ethereum")

    def test_native_symbol_collision_uses_longer_contract_suffix(self) -> None:
        wallet = "0x" + "1" * 40
        raw = {
            "from": "0x" + "2" * 40,
            "to": wallet,
            "hash": "0x" + "a" * 64,
            "blockNumber": "123",
            "timeStamp": "1777573655",
            "value": "1000000000000000000",
            "tokenDecimal": "18",
            "tokenSymbol": "ETH",
            "contractAddress": "0x" + "3" * 40,
        }

        row = _parse_tokentx_row(raw, wallet, "ethereum")

        self.assertEqual(row["asset"], "ETH-0x33333333")

    def test_internal_invalid_amount_raises_instead_of_zeroing(self) -> None:
        wallet = "0x" + "1" * 40
        raw = {
            "from": "0x" + "2" * 40,
            "to": wallet,
            "isError": "0",
            "hash": "0x" + "a" * 64,
            "blockNumber": "123",
            "timeStamp": "1777573655",
            "value": "0x10",
        }

        with self.assertRaisesRegex(ValueError, "txlistinternal.value"):
            _parse_internal_row(raw, wallet, "ethereum", 0)

    def test_invalid_block_number_raises_with_context(self) -> None:
        wallet = "0x" + "1" * 40
        raw = {
            "from": wallet,
            "to": "0x" + "2" * 40,
            "isError": "0",
            "hash": "0x" + "a" * 64,
            "blockNumber": "latest",
            "timeStamp": "1777573655",
            "value": "1000000000000000000",
            "gasUsed": "21000",
            "gasPrice": "1000000000",
        }

        with self.assertRaisesRegex(ValueError, "blockNumber"):
            _parse_txlist_row(raw, wallet, "ethereum")


if __name__ == "__main__":
    unittest.main()
