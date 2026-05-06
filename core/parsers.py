"""
Row parsers: convert raw Etherscan API dicts to internal transaction dicts.
No DB access, no HTTP. Pure data transformation.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from core.models import (
    CHAINS,
    TRANSFER_IN, TRANSFER_OUT, BRIDGE_IN, BRIDGE_OUT, GAS_FEE,
    is_bridge_contract,
    to_decimal_strict, to_db,
)


def _unix_to_iso(ts_str: str) -> str:
    try:
        dt = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, OSError):
        return ""


def _parse_block_number(raw: dict) -> int:
    try:
        return int(raw.get("blockNumber", "0") or "0")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid blockNumber: {raw.get('blockNumber')!r}") from exc


def _method_metadata(raw: dict) -> dict:
    method_id = (raw.get("methodId") or "").strip() or None
    method_name = (raw.get("functionName") or "").strip() or None
    if method_id == "0x":
        method_id = None
    return {"method_id": method_id, "method_name": method_name}


def _address_metadata(raw: dict) -> dict:
    from_address = (raw.get("from") or "").lower().strip() or None
    to_address = (raw.get("to") or "").lower().strip() or None
    return {"from_address": from_address, "to_address": to_address}


def _parse_tokentx_row(raw: dict, wallet: str, chain: str) -> dict | None:
    from_addr = raw.get("from", "").lower()
    to_addr   = raw.get("to",   "").lower()

    if from_addr != wallet and to_addr != wallet:
        return None

    try:
        decimals = int(raw.get("tokenDecimal", "18") or "18")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid tokenDecimal: {raw.get('tokenDecimal')!r}") from exc
    amount_raw = to_decimal_strict(raw.get("value", "0"), "tokentx.value") / (
        Decimal("10") ** decimals
    )

    is_inflow    = (to_addr == wallet)
    counterparty = from_addr if is_inflow else to_addr
    bridge_name  = is_bridge_contract(chain, counterparty)

    if bridge_name:
        direction = BRIDGE_IN if is_inflow else BRIDGE_OUT
    else:
        direction = TRANSFER_IN if is_inflow else TRANSFER_OUT
    signed = abs(amount_raw) if is_inflow else -abs(amount_raw)

    symbol   = raw.get("tokenSymbol", "").strip()
    contract = raw.get("contractAddress", "").lower() or None

    # ERC-20 whose symbol collides with the chain's native token → disambiguate.
    if contract and symbol == CHAINS[chain]["native"]:
        symbol = f"{symbol}-{contract[:10]}"

    return {
        "id":               str(uuid.uuid4()),
        "chain":            chain,
        "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
        "block_number":     _parse_block_number(raw),
        "tx_hash":          raw.get("hash", ""),
        **_address_metadata(raw),
        "type":             direction,
        "asset":            symbol,
        "contract_address": contract,
        "amount":           to_db(signed),
        "source":           "tokentx",
        **_method_metadata(raw),
    }


def _parse_txlist_row(raw: dict, wallet: str, chain: str) -> list[dict]:
    """One txlist row may produce up to two DB rows: value transfer + gas fee."""
    native       = CHAINS[chain]["native"]
    from_addr    = raw.get("from", "").lower()
    to_addr      = raw.get("to",   "").lower()
    is_error     = raw.get("isError", "0") == "1"
    outer_hash   = raw.get("hash", "")
    block_number = _parse_block_number(raw)
    ts           = _unix_to_iso(raw.get("timeStamp", "0"))

    rows: list[dict] = []

    # Value transfer — only for successful transactions
    if not is_error:
        value_wei = to_decimal_strict(raw.get("value", "0"), "txlist.value")
        if value_wei > 0 and (from_addr == wallet or to_addr == wallet):
            is_inflow    = (to_addr == wallet)
            counterparty = from_addr if is_inflow else to_addr
            if is_bridge_contract(chain, counterparty):
                direction = BRIDGE_IN if is_inflow else BRIDGE_OUT
            else:
                direction = TRANSFER_IN if is_inflow else TRANSFER_OUT
            amount_eth = value_wei / Decimal("10") ** 18
            signed     = abs(amount_eth) if is_inflow else -abs(amount_eth)
            rows.append({
                "id":               str(uuid.uuid4()),
                "chain":            chain,
                "timestamp":        ts,
                "block_number":     block_number,
                "tx_hash":          outer_hash,
                **_address_metadata(raw),
                "type":             direction,
                "asset":            native,
                "contract_address": None,
                "amount":           to_db(signed),
                "source":           "txlist",
                **_method_metadata(raw),
            })

    # Gas fee — wallet is sender, regardless of success/failure
    if from_addr == wallet:
        gas_used  = to_decimal_strict(raw.get("gasUsed", "0"), "txlist.gasUsed")
        gas_price = to_decimal_strict(raw.get("gasPrice", "0"), "txlist.gasPrice")
        fee = (gas_used * gas_price) / Decimal("10") ** 18
        if fee > 0:
            rows.append({
                "id":               str(uuid.uuid4()),
                "chain":            chain,
                "timestamp":        ts,
                "block_number":     block_number,
                "tx_hash":          outer_hash + "_fee",
                **_address_metadata(raw),
                "type":             GAS_FEE,
                "asset":            native,
                "contract_address": None,
                "amount":           to_db(-fee),
                "source":           "txlist",
                **_method_metadata(raw),
            })

    return rows


def _parse_internal_row(raw: dict, wallet: str, chain: str, idx: int) -> dict | None:
    """Internal native transfer (DEX swap return, unstake payout, etc.)."""
    if raw.get("isError", "0") == "1":
        return None

    value_wei = to_decimal_strict(raw.get("value", "0"), "txlistinternal.value")
    if value_wei == 0:
        return None

    from_addr = raw.get("from", "").lower()
    to_addr   = raw.get("to",   "").lower()

    if from_addr != wallet and to_addr != wallet:
        return None

    native       = CHAINS[chain]["native"]
    is_inflow    = (to_addr == wallet)
    counterparty = from_addr if is_inflow else to_addr
    if is_bridge_contract(chain, counterparty):
        direction = BRIDGE_IN if is_inflow else BRIDGE_OUT
    else:
        direction = TRANSFER_IN if is_inflow else TRANSFER_OUT
    amount     = value_wei / Decimal("10") ** 18
    signed     = abs(amount) if is_inflow else -abs(amount)
    outer_hash = raw.get("hash", "")

    return {
        "id":               str(uuid.uuid4()),
        "chain":            chain,
        "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
        "block_number":     _parse_block_number(raw),
        "tx_hash":          f"{outer_hash}_int_{idx}" if outer_hash else f"_int_{idx}",
        **_address_metadata(raw),
        "type":             direction,
        "asset":            native,
        "contract_address": None,
        "amount":           to_db(signed),
        "source":           "txlistinternal",
        **_method_metadata(raw),
    }
