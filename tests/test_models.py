import unittest
from decimal import Decimal

from core.models import COINGECKO_IDS, coingecko_id_for, format_eur, format_token, get_staked_info
from core.token_identity import (
    ARB_ARBITRUM_CONTRACT,
    ATH_ARBITRUM_CONTRACT,
    ATH_ETHEREUM_CONTRACT,
    BEAM_ERC20_CONTRACT,
    PRICING_STAKE_EVENT,
    WBEAM_BEAM_CONTRACT,
    canonical_asset_for,
    staking_wrapper_for,
)


SAFE_USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
FAKE_USDC = "0x" + "9" * 40
ARBITRUM_STPEAR = "0xce3be5204017bb1bd279937f92df09fd7f539b92"
ETHEREUM_XOPN = "0x686e8500b6be8812eb198aabbbfa14c95c03fc88"


class CoingeckoMappingTests(unittest.TestCase):
    def test_native_tokens_map_with_none_contract(self) -> None:
        self.assertEqual(coingecko_id_for("ethereum", None, "ETH"), "ethereum")
        self.assertEqual(coingecko_id_for("arbitrum", None, "ETH"), "ethereum")
        self.assertEqual(coingecko_id_for("base", None, "ETH"), "ethereum")
        self.assertEqual(coingecko_id_for("optimism", None, "ETH"), "ethereum")
        self.assertEqual(coingecko_id_for("polygon", None, "POL"), "polygon-ecosystem-token")
        self.assertEqual(coingecko_id_for("beam", None, "BEAM"), "beam-2")

    def test_non_native_without_contract_is_unknown(self) -> None:
        self.assertIsNone(coingecko_id_for("ethereum", None, "USDC"))

    def test_contract_mapping_has_no_symbol_fallback(self) -> None:
        self.assertEqual(coingecko_id_for("ethereum", SAFE_USDC, "USDC"), "usd-coin")
        self.assertIsNone(coingecko_id_for("ethereum", FAKE_USDC, "USDC"))

    def test_contract_lookup_normalizes_case(self) -> None:
        self.assertEqual(coingecko_id_for("ethereum", SAFE_USDC.upper(), "USDC"), "usd-coin")

    def test_weth_contracts_map_to_weth(self) -> None:
        self.assertEqual(
            coingecko_id_for("base", "0x4200000000000000000000000000000000000006", "WETH"),
            "weth",
        )

    def test_arb_on_arbitrum_maps_by_contract(self) -> None:
        self.assertEqual(coingecko_id_for("arbitrum", ARB_ARBITRUM_CONTRACT, "ARB"), "arbitrum")
        self.assertEqual(canonical_asset_for("arbitrum", ARB_ARBITRUM_CONTRACT, "ARB"), "ARB")

    def test_beam_variants_map_to_canonical_beam(self) -> None:
        self.assertEqual(coingecko_id_for("beam", None, "BEAM"), "beam-2")
        self.assertEqual(coingecko_id_for("beam", WBEAM_BEAM_CONTRACT, "WBEAM"), "beam-2")
        self.assertEqual(coingecko_id_for("ethereum", BEAM_ERC20_CONTRACT, "BEAM"), "beam-2")
        self.assertEqual(canonical_asset_for("beam", WBEAM_BEAM_CONTRACT, "WBEAM"), "BEAM")

    def test_ath_multichain_maps_to_canonical_ath(self) -> None:
        self.assertEqual(coingecko_id_for("ethereum", ATH_ETHEREUM_CONTRACT, "ATH"), "aethir")
        self.assertEqual(coingecko_id_for("arbitrum", ATH_ARBITRUM_CONTRACT, "ATH"), "aethir")
        self.assertEqual(canonical_asset_for("arbitrum", ATH_ARBITRUM_CONTRACT, "ATH"), "ATH")

    def test_ath_on_beam_is_unknown_until_contract_is_confirmed(self) -> None:
        self.assertIsNone(coingecko_id_for("beam", FAKE_USDC, "ATH"))

    def test_staked_wrappers_have_stake_event_policy_not_direct_price(self) -> None:
        self.assertIsNone(coingecko_id_for("ethereum", None, "xOPN"))
        self.assertIsNone(coingecko_id_for("arbitrum", None, "stPEAR"))
        self.assertIsNone(coingecko_id_for("ethereum", ETHEREUM_XOPN, "xOPN"))
        self.assertIsNone(coingecko_id_for("arbitrum", ARBITRUM_STPEAR, "stPEAR"))
        self.assertEqual(canonical_asset_for("ethereum", ETHEREUM_XOPN, "xOPN"), "OPN")
        self.assertEqual(canonical_asset_for("arbitrum", ARBITRUM_STPEAR, "stPEAR"), "PEAR")

        xopn = staking_wrapper_for("ethereum", ETHEREUM_XOPN, "xOPN")
        stpear = staking_wrapper_for("arbitrum", ARBITRUM_STPEAR, "stPEAR")
        self.assertEqual(xopn.underlying_asset, "OPN")
        self.assertEqual(stpear.underlying_asset, "PEAR")
        self.assertEqual(xopn.pricing_policy, PRICING_STAKE_EVENT)
        self.assertEqual(stpear.pricing_policy, PRICING_STAKE_EVENT)

    def test_staked_wrapper_symbol_does_not_override_unknown_contract(self) -> None:
        self.assertIsNone(coingecko_id_for("arbitrum", FAKE_USDC, "stPEAR"))

    def test_staked_compat_info_keeps_underlying_for_review_sync(self) -> None:
        info = get_staked_info("arbitrum", "stPEAR")

        self.assertEqual(info["underlying"], "PEAR")
        self.assertEqual(info["underlying_coingecko_id"], "pear-protocol")
        self.assertEqual(info["pricing_policy"], PRICING_STAKE_EVENT)

    def test_fake_known_symbols_do_not_get_prices(self) -> None:
        for chain, symbol in (
            ("arbitrum", "ARB"),
            ("beam", "BEAM"),
            ("ethereum", "ATH"),
            ("ethereum", "OPN"),
            ("arbitrum", "PEAR"),
        ):
            with self.subTest(chain=chain, symbol=symbol):
                self.assertIsNone(coingecko_id_for(chain, FAKE_USDC, symbol))

    def test_public_mapping_uses_contract_keys(self) -> None:
        self.assertEqual(COINGECKO_IDS[("ethereum", SAFE_USDC)], "usd-coin")
        self.assertNotIn(("ethereum", ETHEREUM_XOPN), COINGECKO_IDS)
        self.assertNotIn(("arbitrum", ARBITRUM_STPEAR), COINGECKO_IDS)
        self.assertNotIn(("ethereum", "USDC"), COINGECKO_IDS)

    def test_format_eur_uses_dutch_decimal_format(self) -> None:
        self.assertEqual(format_eur(Decimal("1234.5")), "€ 1.234,50")
        self.assertEqual(format_eur(None), "—")

    def test_format_token_uses_dutch_decimal_format(self) -> None:
        self.assertEqual(format_token(Decimal("1234567.891"), decimals=2), "1.234.567,89")
        self.assertEqual(format_token(Decimal("1"), decimals=0), "1")
        self.assertEqual(format_token(None), "—")


if __name__ == "__main__":
    unittest.main()
