from decimal import Decimal

import pandas as pd

from core.ledger import (
    action_target_label,
    explorer_tx_url,
    method_label,
    normalize_tx_hash,
    short_tx_hash,
    token_signal,
)
from core.models import CHAINS, format_eur, format_token, to_decimal


TABLE_COLUMNS = [
    "Datum",
    "Wallet",
    "Chain",
    "Type",
    "Actie",
    "Signaal",
    "Bedrag",
    "Asset",
    "EUR (op tx-datum)",
    "Tx",
    "Bron",
    "Explorer",
]
CSV_COLUMNS = [
    "timestamp",
    "wallet",
    "chain",
    "type",
    "method_id",
    "method_name",
    "signal",
    "amount",
    "asset",
    "eur_value",
    "tx_hash",
    "normalized_tx_hash",
    "source",
    "explorer_url",
]
GROUPED_TABLE_COLUMNS = [
    "Datum",
    "Wallet",
    "Chain",
    "Type",
    "Actie",
    "Signaal",
    "Uit",
    "In",
    "Gas",
    "EUR (op tx-datum)",
    "Tx",
    "Bron",
    "Explorer",
]
GROUPED_CSV_COLUMNS = [
    "timestamp",
    "wallet",
    "chain",
    "type",
    "action",
    "signals",
    "out",
    "in",
    "gas",
    "eur_value",
    "eur_partial",
    "assets",
    "tx_hash",
    "source",
    "booking_rows",
    "explorer_url",
]


def chain_label(chain: str) -> str:
    return CHAINS.get(chain, {}).get("label", chain)


def without_eur(rows: list[dict]) -> list[dict]:
    return [
        {**row, "coingecko_id": None, "eur_price": None, "eur_value": None, "eur_missing": False}
        for row in rows
    ]


def table_df(rows: list[dict]) -> pd.DataFrame:
    display_rows = []
    for row in rows:
        display_rows.append({
            "Datum": _display_timestamp(row["timestamp"]),
            "Wallet": row["wallet"],
            "Chain": chain_label(row["chain"]),
            "Type": _type_label(row["type"]),
            "Actie": _row_action_label(row),
            "Signaal": token_signal(row) or "-",
            "Bedrag": _display_amount(row["amount"]),
            "Asset": row["asset"],
            "EUR (op tx-datum)": _display_eur(
                row.get("eur_value"),
                bool(row.get("valuation_manual")),
            ),
            "Tx": short_tx_hash(row["tx_hash"]),
            "Bron": row["source"],
            "Explorer": explorer_tx_url(row["chain"], row["tx_hash"]),
        })
    return pd.DataFrame(display_rows, columns=TABLE_COLUMNS)


def grouped_table_df(groups: list[dict]) -> pd.DataFrame:
    display_rows = []
    for group in groups:
        out_rows, in_rows, gas_rows = _split_group_rows(group["rows"])
        display_rows.append({
            "Datum": _display_timestamp(group["timestamp"]),
            "Wallet": group["wallet"],
            "Chain": chain_label(group["chain"]),
            "Type": _group_type_label(group["type"]),
            "Actie": _group_action_label(group),
            "Signaal": ", ".join(group["signals"]) or "-",
            "Uit": _summarize_rows(out_rows, absolute=True),
            "In": _summarize_rows(in_rows, absolute=True),
            "Gas": _summarize_rows(gas_rows, absolute=True),
            "EUR (op tx-datum)": _summarize_eur(group["rows"]),
            "Tx": short_tx_hash(group["tx_hash"]),
            "Bron": ", ".join(group["sources"]),
            "Explorer": explorer_tx_url(group["chain"], group["tx_hash"]),
        })
    return pd.DataFrame(display_rows, columns=GROUPED_TABLE_COLUMNS)


def csv_df(rows: list[dict]) -> pd.DataFrame:
    csv_rows = []
    for row in rows:
        normalized = normalize_tx_hash(row["tx_hash"])
        csv_rows.append({
            "timestamp": row["timestamp"],
            "wallet": row["wallet"],
            "chain": row["chain"],
            "type": row["type"],
            "method_id": row["method_id"],
            "method_name": row["method_name"],
            "signal": token_signal(row),
            "amount": row["amount"],
            "asset": row["asset"],
            "eur_value": _csv_eur(row.get("eur_value")),
            "tx_hash": row["tx_hash"],
            "normalized_tx_hash": normalized,
            "source": row["source"],
            "explorer_url": explorer_tx_url(row["chain"], row["tx_hash"]),
        })
    return pd.DataFrame(csv_rows, columns=CSV_COLUMNS)


def grouped_csv_df(groups: list[dict]) -> pd.DataFrame:
    csv_rows = []
    for group in groups:
        out_rows, in_rows, gas_rows = _split_group_rows(group["rows"])
        csv_rows.append({
            "timestamp": group["timestamp"],
            "wallet": group["wallet"],
            "chain": group["chain"],
            "type": group["type"],
            "action": _group_action_label(group),
            "signals": ", ".join(group["signals"]),
            "out": _summarize_rows(out_rows, absolute=True),
            "in": _summarize_rows(in_rows, absolute=True),
            "gas": _summarize_rows(gas_rows, absolute=True),
            "eur_value": _csv_eur(_group_eur_value(group["rows"])),
            "eur_partial": any(row.get("eur_missing") for row in group["rows"]),
            "assets": ", ".join(group["assets"]),
            "tx_hash": group["tx_hash"],
            "source": ", ".join(group["sources"]),
            "booking_rows": group["row_count"],
            "explorer_url": explorer_tx_url(group["chain"], group["tx_hash"]),
        })
    return pd.DataFrame(csv_rows, columns=GROUPED_CSV_COLUMNS)


def _display_timestamp(timestamp: str) -> str:
    return timestamp.replace("T", " ")[:19]


def _display_amount(amount: str) -> str:
    value = to_decimal(amount)
    decimals = 8 if abs(value) < Decimal("0.01") else 6
    return format_token(value, decimals=decimals)


def _display_signed_amount(value: Decimal) -> str:
    decimals = 8 if abs(value) < Decimal("0.01") else 6
    formatted = format_token(value, decimals=decimals)
    return f"+{formatted}" if value > 0 else formatted


def _display_plain_amount(value: Decimal) -> str:
    decimals = 8 if abs(value) < Decimal("0.01") else 6
    return format_token(value, decimals=decimals)


def _display_eur(value: Decimal | None, manual: bool = False) -> str:
    suffix = " (handmatig 0)" if manual else ""
    return f"{format_eur(value)}{suffix}"


def _summarize_rows(rows: list[dict], absolute: bool = False) -> str:
    totals: dict[str, Decimal] = {}
    order: list[str] = []
    for row in rows:
        asset = row["asset"]
        if asset not in totals:
            totals[asset] = Decimal("0")
            order.append(asset)
        totals[asset] += to_decimal(row["amount"])

    parts = []
    for asset in order:
        amount = totals[asset]
        if amount == 0:
            continue
        formatted = _display_plain_amount(abs(amount)) if absolute else _display_signed_amount(amount)
        parts.append(f"{formatted} {asset}")
    return " | ".join(parts) or "-"


def _summarize_eur(rows: list[dict]) -> str:
    known = [row["eur_value"] for row in rows if row.get("eur_value") is not None]
    if not known:
        return "—"
    total = sum(known, Decimal("0"))
    suffix = " (deels)" if any(row.get("eur_missing") for row in rows) else ""
    if any(row.get("valuation_manual") for row in rows):
        suffix = f"{suffix} (handmatig 0)"
    return f"{_display_eur(total)}{suffix}"


def _csv_eur(value: Decimal | None) -> str:
    return "" if value is None else str(value)


def _split_group_rows(rows: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    out_rows = []
    in_rows = []
    gas_rows = []
    for row in rows:
        amount = to_decimal(row["amount"])
        if row["type"] == "GAS_FEE":
            gas_rows.append(row)
        elif amount < 0:
            out_rows.append(row)
        elif amount > 0:
            in_rows.append(row)
    return out_rows, in_rows, gas_rows


def _type_label(tx_type: str) -> str:
    labels = {
        "SWAP": "Swap",
        "MEERDERE": "Meerdere",
        "TRANSFER_IN": "Inkomend",
        "TRANSFER_OUT": "Uitgaand",
        "BRIDGE_IN": "Bridge in",
        "BRIDGE_OUT": "Bridge uit",
        "GAS_FEE": "Gas fee",
    }
    return labels.get(tx_type, tx_type)


def _group_type_label(tx_type: str) -> str:
    if tx_type == "GAS_FEE":
        return "Contract call"
    return _type_label(tx_type)


def _group_action_label(group: dict) -> str:
    methods = group.get("methods") or []
    targets = group.get("action_targets") or []
    named_methods = [m for m in methods if not m.startswith("0x")]
    if named_methods:
        return ", ".join(named_methods[:2])
    if targets:
        return ", ".join(targets[:2])
    if methods:
        return ", ".join(methods[:2])
    if group.get("type") == "GAS_FEE":
        return "Onbekend"
    return "-"


def _row_action_label(row: dict) -> str:
    label = method_label(row.get("method_name"), row.get("method_id"))
    if label and not label.startswith("0x"):
        return label
    target = action_target_label(row.get("chain", ""), row.get("to_address"))
    return target or label or "-"


def _group_eur_value(rows: list[dict]) -> Decimal | None:
    known = [row["eur_value"] for row in rows if row.get("eur_value") is not None]
    return sum(known, Decimal("0")) if known else None
