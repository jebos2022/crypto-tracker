"""
Pure function: synthesize missing WRAP/WETH TRANSFER_IN rows.

No HTTP, no DB. Input = buffer + txlist_rows already parsed. Output = new rows
to append. Caller (_add) handles dedup and block-cursor bookkeeping.
"""

import uuid
from decimal import Decimal

from core.models import (
    CHAINS, WETH_CONTRACTS,
    TRANSFER_IN, TRANSFER_OUT,
    to_decimal, to_db,
)
from core.parsers import _unix_to_iso


def synthesize_wrap_rows(
    buffer: list[dict],
    txlist_rows: list[dict],
    chain: str,
) -> list[dict]:
    """
    Return synthetic TRANSFER_IN rows for native-wrap events that Etherscan
    omits from tokentx (e.g. WETH mint, ETH-named wrapper tokens).

    Section 4 — Native-wrap reconciliation
    Some contracts (WETH and similar) wrap native ETH into an ERC-20 with symbol
    "ETH". Etherscan tokentx omits the Transfer(0x0, wallet, amount) mint event.
    We detect missing mints by matching txlist deposits (to=contract, value>0)
    against TRANSFER_INs in the buffer, and synthesise the missing rows.
    """
    result: list[dict] = []

    native = CHAINS[chain]["native"]
    wrap_contracts: dict[str, str] = {}  # contract_addr → asset symbol

    weth_addr = WETH_CONTRACTS.get(chain)
    if weth_addr:
        wrap_contracts[weth_addr] = "WETH"

    for r in buffer:
        if r.get("source") == "tokentx" and r.get("contract_address"):
            sym = r["asset"]
            if sym.startswith(native + "-"):
                wrap_contracts[r["contract_address"]] = sym

    for contract_addr, sym in wrap_contracts.items():
        ins_seen = {
            r["tx_hash"] for r in buffer
            if r["asset"] == sym and r["type"] == TRANSFER_IN
        }
        for raw in txlist_rows:
            if raw.get("isError", "0") == "1":
                continue
            if raw.get("to", "").lower() != contract_addr:
                continue
            value_wei = to_decimal(raw.get("value", "0"))
            if value_wei <= 0:
                continue
            h = raw.get("hash", "")
            if h in ins_seen or any(k.startswith(h + "_dup") for k in ins_seen):
                continue
            amount = value_wei / Decimal("10") ** 18
            result.append({
                "id":               str(uuid.uuid4()),
                "chain":            chain,
                "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
                "block_number":     int(raw.get("blockNumber", "0") or "0"),
                "tx_hash":          f"{h}_wrap_{contract_addr[:6]}",
                "type":             TRANSFER_IN,
                "asset":            sym,
                "contract_address": contract_addr,
                "amount":           to_db(amount),
                "source":           "txlist",
            })

    # 4b — Amount-based fallback for ETH-renamed tokens routed via a DEX/router.
    # When no TRANSFER_IN exists but there are TRANSFER_OUTs, we look for a txlist
    # entry whose value exactly matches the total outflow — only safe when exactly
    # one candidate exists (avoids false matches on common round amounts).
    for contract_addr, sym in wrap_contracts.items():
        if sym == "WETH":
            continue
        buf_ins  = [r for r in buffer if r["asset"] == sym and r["type"] == TRANSFER_IN]
        buf_outs = [r for r in buffer if r["asset"] == sym and r["type"] == TRANSFER_OUT]
        if not buf_outs or buf_ins:
            continue
        deficit = sum(abs(Decimal(r["amount"])) for r in buf_outs)
        candidates = [
            raw for raw in txlist_rows
            if raw.get("isError", "0") != "1"
            and to_decimal(raw.get("value", "0")) / Decimal("10") ** 18 == deficit
        ]
        if len(candidates) != 1:
            continue
        raw = candidates[0]
        h = raw.get("hash", "")
        result.append({
            "id":               str(uuid.uuid4()),
            "chain":            chain,
            "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
            "block_number":     int(raw.get("blockNumber", "0") or "0"),
            "tx_hash":          f"{h}_wrap_amt_{contract_addr[:6]}",
            "type":             TRANSFER_IN,
            "asset":            sym,
            "contract_address": contract_addr,
            "amount":           to_db(deficit),
            "source":           "txlist",
        })

    return result
