from decimal import Decimal, InvalidOperation

from core.token_identity import (
    COINGECKO_IDS,
    STAKED_TOKENS,
    USDC_CONTRACTS,
    WETH_CONTRACTS,
    coingecko_id_for,
    get_staked_info,
    is_known_safe_token_contract,
)

# ---------------------------------------------------------------------------
# Chain registry — single source of truth
# ---------------------------------------------------------------------------

CHAINS: dict[str, dict] = {
    "ethereum": {"chainid": 1,     "native": "ETH",  "label": "Ethereum"},
    "arbitrum": {"chainid": 42161, "native": "ETH",  "label": "Arbitrum"},
    "base":     {"chainid": 8453,  "native": "ETH",  "label": "Base"},
    "optimism": {"chainid": 10,    "native": "ETH",  "label": "Optimism"},
    "polygon":  {"chainid": 137,   "native": "POL",  "label": "Polygon"},
    "beam":     {"chainid": 4337,  "native": "BEAM", "label": "BEAM"},
}

ROUTESCAN_CHAINS: set[str] = {"beam"}

# CoinGecko uses different identifiers for token-list asset platforms and
# on-chain network endpoints.
COINGECKO_TOKEN_LIST_PLATFORMS: dict[str, str] = {
    "ethereum": "ethereum",
    "arbitrum": "arbitrum-one",
    "base": "base",
    "optimism": "optimistic-ethereum",
    "polygon": "polygon-pos",
}

COINGECKO_ONCHAIN_NETWORKS: dict[str, str] = {
    "ethereum": "eth",
    "arbitrum": "arbitrum",
    "base": "base",
    "optimism": "optimism",
    "polygon": "polygon_pos",
}

ETHERSCAN_BASE = "https://api.etherscan.io/v2/api"
ROUTESCAN_BASE = "https://api.routescan.io/v2/network/mainnet/evm/{chainid}/etherscan/api"
PAGE_SIZE = 10_000

# ---------------------------------------------------------------------------
# Bridge contract registry — known cross-chain bridges per chain.
# Used to tag transfers to/from these contracts as BRIDGE_OUT/IN, so the UI
# can explain a negative balance ("you bridged X to chain we don't track").
# All addresses must be lowercase. Extend as needed.
# ---------------------------------------------------------------------------

BRIDGE_CONTRACTS: dict[str, dict[str, str]] = {
    "ethereum": {
        # Native L1 → L2 bridges
        "0x99c9fc46f92e8a1c0dec1b1747d010903e884be1": "Optimism Gateway",
        "0x3154cf16ccdb4c6d922629664174b904d80f2c35": "Base Bridge",
        "0x72ce9c846789fdb6fc1f34ac4ad25dd9ef7031ef": "Arbitrum L1 Gateway Router",
        "0xa3a7b6f88361f48403514059f1f16c8e78d60eec": "Arbitrum One Inbox",
        "0xa0c68c638235ee32657e8f720a23cec1bfc77c77": "Polygon PoS RootChainManager",
        "0x40ec5b33f54e0e8a33a975908c5ba1c14e5bbbdf": "Polygon ERC20 Predicate",
        # Third-party bridges
        "0x8731d54e9d02c286767d56ac03e8037c07e01e98": "Stargate Router",
        "0x5c7bcd6e7de5423a257d81b442095a1a6ced35c5": "Across SpokePool",
        "0x3ee18b2214aad7c57b9c24c2eb33d6e29ca9e3fb": "Wormhole Token Bridge",
        "0x2796317b0ff8538f253012862c06787adfb8ceb6": "Synapse Bridge",
        "0x66a71dcef29a0ffbdbe3c6a460a3b5bc225cd675": "LayerZero Endpoint",
        "0xbbbbbbbbbb9cc5e90e3b3af64bdaf62c37eeffcb": "Hop Bridge ETH",
    },
    "arbitrum": {
        "0x53bf833a5d6c4dda888f69c22c88c9f356a41614": "Stargate Router",
        "0xe35e9842fceaca96570b734083f4a58e8f7c5f2a": "Across SpokePool",
        "0xa67ec8737021a7e91e883a3277384e6018bb5776": "LayerZero Endpoint",
        "0x6f4e8eba4d337f874ab57478acc2cb5bacdc19c9": "Synapse Bridge",
    },
    "base": {
        "0x4200000000000000000000000000000000000010": "L2 Standard Bridge",
        "0x45f1a95a4d3f3836523f5c83673c797f4d4d263b": "Stargate Router",
        "0x09aea4b2242abc8bb4bb78d537a67a245a7bec64": "Across SpokePool",
        "0xb6319cc6c8c27a8f5daf0dd3df91ea35c4720dd7": "LayerZero Endpoint",
    },
    "optimism": {
        "0x4200000000000000000000000000000000000010": "L2 Standard Bridge",
        "0xb0d502e938ed5f4df2e681fe6e419ff29631d62b": "Stargate Router",
        "0x9ddb2da7dd76612e0df237b89af2cf4413733212": "Across SpokePool",
        "0x3c2269811836af69497e5f486a85d7316753cf62": "LayerZero Endpoint",
    },
    "polygon": {
        "0x45a01e4e04f14f7a4a6702c74187c5f6222033cd": "Stargate Router",
        "0x9805c11ed35a91c5c87b29b1aa2e2bf42960aab9": "Across SpokePool",
        "0x3c2269811836af69497e5f486a85d7316753cf62": "LayerZero Endpoint",
        "0x8f5bbb2bb8c2ee94639e55d5f41de9b4839c1280": "Synapse Bridge",
    },
    "beam": {
        # Add BEAM-specific bridge contracts here when known.
    },
}


def is_bridge_contract(chain: str, address: str | None) -> str | None:
    """Return the bridge name if `address` is a known bridge on `chain`, else None."""
    if not address:
        return None
    return BRIDGE_CONTRACTS.get(chain, {}).get(address.lower())


# ---------------------------------------------------------------------------
# Transaction types
# ---------------------------------------------------------------------------

TRANSFER_IN  = "TRANSFER_IN"
TRANSFER_OUT = "TRANSFER_OUT"
BRIDGE_IN    = "BRIDGE_IN"   # inflow from a known bridge contract
BRIDGE_OUT   = "BRIDGE_OUT"  # outflow to a known bridge contract
GAS_FEE      = "GAS_FEE"

# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

def to_decimal(raw) -> Decimal:
    """Convert any value to Decimal safely. Returns 0 on failure."""
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return Decimal("0")


def to_db(d: Decimal) -> str:
    """Store Decimal as TEXT for SQLite."""
    return str(d)


def format_token(d: Decimal | None, decimals: int = 6) -> str:
    """Dutch locale formatting: period for thousands, comma for decimal."""
    if d is None:
        return "—"
    rounded = round(d, decimals)
    # Format with enough decimal places, then apply Dutch locale
    formatted = f"{rounded:,.{decimals}f}"
    # Python uses comma for thousands, period for decimal — swap for Dutch
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")
