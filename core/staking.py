"""
Staking rate computation: exchange rate between a staked wrapper token and its underlying.

Formula: OPN_held_by_vault / total_xOPN_supply
Works for simple single-asset vaults where the underlying is held at the staking contract address.
"""

from decimal import Decimal

from core.models import STAKED_TOKENS
from core import api


def get_staking_rate(chain: str, staked_token: str) -> Decimal | None:
    """
    Exchange rate: underlying tokens per 1 staked token.
    Returns None if the token is unknown or the on-chain call fails.
    """
    info = STAKED_TOKENS.get(chain, {}).get(staked_token)
    if not info:
        return None
    try:
        vault_balance = api.fetch_token_balance(
            address=info["staking_contract"],
            contract_address=info["underlying_contract"],
            chain=chain,
        )
        total_supply = api.fetch_token_supply(info["staking_contract"], chain)
        if total_supply == 0:
            return None
        # Both values are raw (same 18-decimal base), so the ratio is the exchange rate.
        return Decimal(vault_balance) / Decimal(total_supply)
    except Exception:
        return None


def all_staking_rates() -> dict[tuple[str, str], Decimal]:
    """Fetch all known staking rates. Returns {(chain, staked_token): rate}."""
    rates: dict[tuple[str, str], Decimal] = {}
    for chain, tokens in STAKED_TOKENS.items():
        for staked_token in tokens:
            rate = get_staking_rate(chain, staked_token)
            if rate is not None:
                rates[(chain, staked_token)] = rate
    return rates


BEAM_STAKING_CONTRACT = "0x2fd428a5484d113294b44e69cb9f269abc1d5b54"


def fetch_beam_staking_balance(address: str) -> Decimal | None:
    """
    Live calculation of staked BEAM through the node staking contract.
    Returns the net staked amount, or None when the API call fails.
    """
    try:
        deposits = Decimal("0")
        for row in api.fetch_txlist(address, "beam"):
            if row.get("isError", "0") == "1":
                continue
            if row.get("to", "").lower() != BEAM_STAKING_CONTRACT:
                continue
            v = Decimal(row.get("value", "0") or "0")
            if v > 0:
                deposits += v

        withdrawals = Decimal("0")
        for row in api.fetch_txlistinternal(address, "beam"):
            if row.get("from", "").lower() != BEAM_STAKING_CONTRACT:
                continue
            v = Decimal(row.get("value", "0") or "0")
            if v > 0:
                withdrawals += v

        wei = Decimal("10") ** 18
        return (deposits - withdrawals) / wei
    except Exception:
        return None
