from decimal import Decimal, InvalidOperation

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

# WETH contract addresses per chain — used to detect missing wrap Transfer events
WETH_CONTRACTS: dict[str, str] = {
    "ethereum": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
    "arbitrum": "0x82af49447d8a07e3bd95bd0d56f35241523fbab1",
    "base":     "0x4200000000000000000000000000000000000006",
    "optimism": "0x4200000000000000000000000000000000000006",
    "polygon":  "0x7ceb23fd6bc0add59e62ac25578270cff1b9f619",
}

ETHERSCAN_BASE = "https://api.etherscan.io/v2/api"
ROUTESCAN_BASE = "https://api.routescan.io/v2/network/mainnet/evm/{chainid}/etherscan/api"
PAGE_SIZE = 10_000

# ---------------------------------------------------------------------------
# Transaction types
# ---------------------------------------------------------------------------

TRANSFER_IN  = "TRANSFER_IN"
TRANSFER_OUT = "TRANSFER_OUT"
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
