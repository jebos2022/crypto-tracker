import unittest
from decimal import Decimal

from core.balances import beam_staking_positions_from_rows, summarize_balances
from core.staking import BEAM_STAKING_CONTRACT
from core.token_identity import WBEAM_BEAM_CONTRACT


FAKE_CONTRACT = "0x" + "9" * 40
STPEAR = "0xce3be5204017bb1bd279937f92df09fd7f539b92"


class BalanceSummaryTests(unittest.TestCase):
    def test_known_variants_group_by_canonical_asset(self) -> None:
        summaries, positions = summarize_balances([
            {
                "wallet": "main",
                "chain": "beam",
                "asset": "BEAM",
                "contract_address": None,
                "balance": Decimal("100"),
                "eur_value": Decimal("2"),
                "eur_missing": False,
            },
            {
                "wallet": "cold",
                "chain": "beam",
                "asset": "WBEAM",
                "contract_address": WBEAM_BEAM_CONTRACT,
                "balance": Decimal("50"),
                "eur_value": Decimal("1"),
                "eur_missing": False,
            },
        ])

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0]["asset"], "BEAM")
        self.assertEqual(summaries[0]["balance"], Decimal("150"))
        self.assertEqual(summaries[0]["eur_value"], Decimal("3"))
        self.assertEqual(summaries[0]["wallets"], {"main", "cold"})
        self.assertEqual(positions, [])

    def test_unknown_same_symbol_does_not_merge_with_known_asset(self) -> None:
        summaries, _positions = summarize_balances([
            {
                "wallet": "main",
                "chain": "beam",
                "asset": "BEAM",
                "contract_address": None,
                "balance": Decimal("100"),
                "eur_value": Decimal("2"),
                "eur_missing": False,
            },
            {
                "wallet": "main",
                "chain": "ethereum",
                "asset": "BEAM",
                "contract_address": FAKE_CONTRACT,
                "balance": Decimal("50"),
                "eur_value": None,
                "eur_missing": True,
            },
        ])

        self.assertEqual([summary["balance"] for summary in summaries], [Decimal("100"), Decimal("50")])

    def test_staking_wrapper_is_position_not_asset_summary(self) -> None:
        summaries, positions = summarize_balances([
            {
                "wallet": "main",
                "chain": "arbitrum",
                "asset": "stPEAR",
                "contract_address": STPEAR,
                "balance": Decimal("80"),
                "eur_value": None,
                "eur_missing": True,
            }
        ])

        self.assertEqual(summaries, [])
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["canonical_asset"], "PEAR")

    def test_beam_staking_deposits_are_synthetic_beam_balance(self) -> None:
        rows = [
            {
                "wallet": "main",
                "amount": "-4500000",
                "from_address": "0x" + "1" * 40,
                "to_address": BEAM_STAKING_CONTRACT,
            },
            {
                "wallet": "main",
                "amount": "-500000",
                "from_address": "0x" + "1" * 40,
                "to_address": BEAM_STAKING_CONTRACT,
            },
        ]

        positions = beam_staking_positions_from_rows(rows)

        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0]["asset"], "BEAM")
        self.assertEqual(positions[0]["display_asset"], "BEAM (gestaked)")
        self.assertEqual(positions[0]["balance"], Decimal("5000000"))

    def test_beam_staking_withdrawal_reduces_synthetic_balance(self) -> None:
        rows = [
            {
                "wallet": "main",
                "amount": "-5000000",
                "from_address": "0x" + "1" * 40,
                "to_address": BEAM_STAKING_CONTRACT,
            },
            {
                "wallet": "main",
                "amount": "1000000",
                "from_address": BEAM_STAKING_CONTRACT,
                "to_address": "0x" + "1" * 40,
            },
        ]

        positions = beam_staking_positions_from_rows(rows)

        self.assertEqual(positions[0]["balance"], Decimal("4000000"))


if __name__ == "__main__":
    unittest.main()
