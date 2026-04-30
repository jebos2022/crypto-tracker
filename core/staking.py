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
