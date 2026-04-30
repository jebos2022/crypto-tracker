import re
from collections import OrderedDict
from datetime import date

from core.models import CHAINS, STAKED_TOKENS, WETH_CONTRACTS, to_decimal
from core.token_review import is_scam


_TX_HASH_RE = re.compile(r"^(0x[a-fA-F0-9]{64})")

EXPLORER_TX_URLS: dict[str, str] = {
    "ethereum": "https://etherscan.io/tx/{tx_hash}",
    "arbitrum": "https://arbiscan.io/tx/{tx_hash}",
    "base": "https://basescan.org/tx/{tx_hash}",
    "optimism": "https://optimistic.etherscan.io/tx/{tx_hash}",
    "polygon": "https://polygonscan.com/tx/{tx_hash}",
    "beam": "https://subnets.avax.network/beam/tx/{tx_hash}",
}

KNOWN_ACTION_TARGETS: dict[str, dict[str, str]] = {
    "ethereum": {
        "0x0000000000001ff3684f28c67538d4d072c22734": "0x Swap",
    },
}

KNOWN_TOKEN_CONTRACTS: set[tuple[str, str]] = {
    ("ethereum", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"),  # USDC
    ("arbitrum", "0xaf88d065e77c8cc2239327c5edb3a432268e5831"),  # USDC
    ("base", "0x833589fcd6edb6e08f4c7c32d4f71b54bdA02913".lower()),  # USDC
    ("optimism", "0x0b2c639c533813f4aa9d7837caf62653d097ff85"),  # USDC
    ("polygon", "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"),  # USDC
}
KNOWN_TOKEN_CONTRACTS |= {
    (chain, contract.lower())
    for chain, contract in WETH_CONTRACTS.items()
}
KNOWN_TOKEN_CONTRACTS |= {
    (chain, info["underlying_contract"].lower())
    for chain, tokens in STAKED_TOKENS.items()
    for info in tokens.values()
}


def normalize_tx_hash(tx_hash: str | None) -> str:
    """
    Return the real chain hash from DB hashes suffixed for row uniqueness.

    The fetcher stores synthetic variants such as `_fee`, `_int_N`, and
    `_dupN`. Explorer links must point to the original on-chain transaction.
    """
    if not tx_hash:
        return ""
    match = _TX_HASH_RE.match(tx_hash.strip())
    return match.group(1) if match else tx_hash.strip()


def short_tx_hash(tx_hash: str | None) -> str:
    normalized = normalize_tx_hash(tx_hash)
    if len(normalized) <= 18:
        return normalized
    return f"{normalized[:10]}...{normalized[-6:]}"


def explorer_tx_url(chain: str, tx_hash: str | None) -> str:
    normalized = normalize_tx_hash(tx_hash)
    if not _TX_HASH_RE.fullmatch(normalized):
        return ""
    template = EXPLORER_TX_URLS.get(chain)
    if template:
        return template.format(tx_hash=normalized)
    chain_info = CHAINS.get(chain)
    if chain_info:
        return f"https://routescan.io/tx/{normalized}?chainid={chain_info['chainid']}"
    return ""


def logical_tx_groups(
    rows: list[dict],
    asset_filter: str | None = None,
    include_gas_only: bool = True,
) -> list[dict]:
    """
    Group ledger booking rows into user-facing on-chain transactions.

    Keep wallet and chain in the grouping key: the same tx hash can be relevant
    from multiple wallet perspectives when "Alle wallets" is selected.
    """
    groups: OrderedDict[tuple[str, str, str], dict] = OrderedDict()
    for row in rows:
        normalized = normalize_tx_hash(row.get("tx_hash"))
        tx_key = normalized or row.get("tx_hash", "")
        key = (row.get("wallet", ""), row.get("chain", ""), tx_key)
        if key not in groups:
            groups[key] = {
                "wallet": row.get("wallet", ""),
                "chain": row.get("chain", ""),
                "timestamp": row.get("timestamp", ""),
                "block_number": row.get("block_number", 0),
                "tx_hash": tx_key,
                "rows": [],
            }
        groups[key]["rows"].append(row)

    result = []
    for group in groups.values():
        booking_rows = group["rows"]
        if asset_filter and not any(row.get("asset") == asset_filter for row in booking_rows):
            continue
        non_gas = [row for row in booking_rows if row.get("type") != "GAS_FEE"]
        if not include_gas_only and not non_gas:
            continue
        group["type"] = logical_tx_type(booking_rows)
        group["has_non_gas"] = bool(non_gas)
        group["assets"] = sorted({row.get("asset", "") for row in booking_rows if row.get("asset")})
        group["sources"] = sorted({row.get("source", "") for row in booking_rows if row.get("source")})
        group["methods"] = _unique_method_labels(booking_rows)
        group["action_targets"] = _unique_action_targets(booking_rows)
        group["signals"] = group_signals(booking_rows)
        group["row_count"] = len(booking_rows)
        result.append(group)
    return result


def logical_tx_type(rows: list[dict]) -> str:
    non_gas = [row for row in rows if row.get("type") != "GAS_FEE"]
    if not non_gas:
        return "GAS_FEE"

    amounts = [to_decimal(row.get("amount", "0")) for row in non_gas]
    has_in = any(amount > 0 for amount in amounts)
    has_out = any(amount < 0 for amount in amounts)
    if has_in and has_out:
        return "SWAP"

    types = {row.get("type", "") for row in non_gas}
    assets = {row.get("asset", "") for row in non_gas}
    if len(non_gas) > 1 or len(types) > 1 or len(assets) > 1:
        return "MEERDERE"
    return non_gas[0].get("type", "")


def method_label(method_name: str | None, method_id: str | None = None) -> str:
    if method_name:
        raw_name = method_name.split("(", 1)[0].strip()
        if raw_name:
            spaced = re.sub(r"[_-]+", " ", raw_name)
            spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", spaced)
            spaced = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", spaced)
            label = " ".join(spaced.split()).title()
            return (
                label
                .replace(" Eth", " ETH")
                .replace(" Weth", " WETH")
                .replace(" Erc", " ERC")
                .replace(" Nft", " NFT")
            )
    if method_id and method_id != "0x":
        return method_id
    return ""


def action_target_label(chain: str, address: str | None) -> str:
    if not address:
        return ""
    return KNOWN_ACTION_TARGETS.get(chain, {}).get(address.lower(), "")


def token_signal(row: dict) -> str:
    contract = (row.get("contract_address") or "").lower()
    if not contract:
        return ""
    asset = row.get("asset", "")
    if is_scam(asset):
        return "Scam-naam"
    if (row.get("chain", ""), contract) in KNOWN_TOKEN_CONTRACTS:
        return ""
    if row.get("has_metadata"):
        if not row.get("verified") and not row.get("has_website") and not row.get("has_social"):
            return "Verdachte metadata"
        return ""
    return "Metadata ontbreekt"


def group_signals(rows: list[dict]) -> list[str]:
    signals = []
    seen = set()
    for row in rows:
        signal = token_signal(row)
        if signal and signal not in seen:
            signals.append(signal)
            seen.add(signal)
    return signals


def _unique_method_labels(rows: list[dict]) -> list[str]:
    labels = []
    seen = set()
    for row in rows:
        label = method_label(row.get("method_name"), row.get("method_id"))
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def _unique_action_targets(rows: list[dict]) -> list[str]:
    labels = []
    seen = set()
    for row in rows:
        label = action_target_label(row.get("chain", ""), row.get("to_address"))
        if label and label not in seen:
            labels.append(label)
            seen.add(label)
    return labels


def csv_filename(
    wallet_label: str,
    chain_label: str,
    asset_label: str,
    today: date | None = None,
) -> str:
    day = today or date.today()
    parts = [
        "transactions",
        _slug(wallet_label),
        _slug(chain_label),
        _slug(asset_label),
        day.isoformat(),
    ]
    return "_".join(parts) + ".csv"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "all"
