import unittest
from decimal import Decimal

from core import staking
from core.models import BEAM_STAKING_CONTRACT


class BeamStakingBalanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_txlist = staking.api.fetch_txlist
        self.original_internal = staking.api.fetch_txlistinternal

    def tearDown(self) -> None:
        staking.api.fetch_txlist = self.original_txlist
        staking.api.fetch_txlistinternal = self.original_internal

    def test_fetch_beam_staking_balance_nets_live_deposits_and_withdrawals(self) -> None:
        staking.api.fetch_txlist = lambda _address, _chain: [
            {
                "to": BEAM_STAKING_CONTRACT.upper(),
                "value": "3000000000000000000",
                "isError": "0",
            },
            {
                "to": BEAM_STAKING_CONTRACT,
                "value": "1000000000000000000",
                "isError": "1",
            },
            {
                "to": "0x" + "9" * 40,
                "value": "1000000000000000000",
                "isError": "0",
            },
        ]
        staking.api.fetch_txlistinternal = lambda _address, _chain: [
            {
                "from": BEAM_STAKING_CONTRACT.upper(),
                "value": "500000000000000000",
            }
        ]

        balance = staking.fetch_beam_staking_balance("0x" + "1" * 40)

        self.assertEqual(balance, Decimal("2.5"))

    def test_fetch_beam_staking_balance_returns_none_and_logs_on_api_error(self) -> None:
        def raise_api_error(_address: str, _chain: str):
            raise RuntimeError("temporary api failure")

        staking.api.fetch_txlist = raise_api_error
        staking.api.fetch_txlistinternal = lambda _address, _chain: []

        with self.assertLogs(staking.LOGGER, level="WARNING") as logs:
            balance = staking.fetch_beam_staking_balance("0x" + "1" * 40)

        self.assertIsNone(balance)
        self.assertIn("BEAM staking balance lookup failed", logs.output[0])


if __name__ == "__main__":
    unittest.main()
