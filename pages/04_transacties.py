from decimal import Decimal

import pandas as pd
import streamlit as st

from core.db import get_connection
from core.ledger import (
    action_target_label,
    csv_filename,
    explorer_tx_url,
    logical_tx_groups,
    method_label,
    normalize_tx_hash,
    short_tx_hash,
    token_signal,
)
from core.ledger_backfill import backfill_transaction_methods
from core.models import CHAINS, format_token, to_decimal
from core.token_review import token_review_join_condition


st.title("Transacties")
st.caption("Inspecteer geaccepteerde on-chain transacties per wallet, chain en token.")


TABLE_COLUMNS = ["Datum", "Wallet", "Chain", "Type", "Actie", "Signaal", "Bedrag", "Asset", "Tx", "Bron", "Explorer"]
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
    "assets",
    "tx_hash",
    "source",
    "booking_rows",
    "explorer_url",
]


def _get_wallets() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, name FROM wallets ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_chains(wallet_id: int | None) -> list[str]:
    sql = f"""
        SELECT DISTINCT t.chain
        FROM transactions t
        JOIN token_review tr
          ON {token_review_join_condition("t", "tr")}
        WHERE tr.accepted = 1
    """
    params: list = []
    if wallet_id is not None:
        sql += " AND t.wallet_id = ?"
        params.append(wallet_id)
    sql += " ORDER BY t.chain"

    conn = get_connection()
    try:
        return [r["chain"] for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _get_assets(wallet_id: int | None, chain: str | None) -> list[str]:
    sql = f"""
        SELECT DISTINCT t.asset
        FROM transactions t
        JOIN token_review tr
          ON {token_review_join_condition("t", "tr")}
        WHERE tr.accepted = 1
    """
    params: list = []
    if wallet_id is not None:
        sql += " AND t.wallet_id = ?"
        params.append(wallet_id)
    if chain is not None:
        sql += " AND t.chain = ?"
        params.append(chain)
    sql += " ORDER BY t.asset"

    conn = get_connection()
    try:
        return [r["asset"] for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _get_transactions(
    wallet_id: int | None,
    chain: str | None,
    descending: bool,
) -> list[dict]:
    sql = f"""
        SELECT
            w.name AS wallet,
            t.chain,
            t.timestamp,
            t.block_number,
            t.tx_hash,
            t.from_address,
            t.to_address,
            t.type,
            t.asset,
            t.contract_address,
            t.amount,
            t.source,
            t.method_id,
            t.method_name,
            tr.review_status,
            tr.review_reason,
            MAX(tm.verified) AS verified,
            MAX(tm.holder_count) AS holder_count,
            MAX(tm.has_website) AS has_website,
            MAX(tm.has_social) AS has_social,
            MAX(CASE WHEN tm.fetched_at IS NOT NULL THEN 1 ELSE 0 END) AS has_metadata
        FROM transactions t
        JOIN wallets w ON w.id = t.wallet_id
        JOIN token_review tr
          ON {token_review_join_condition("t", "tr")}
        LEFT JOIN token_metadata tm
          ON tm.chain = t.chain
         AND tm.contract_address = t.contract_address
        WHERE tr.accepted = 1
    """
    params: list = []
    if wallet_id is not None:
        sql += " AND t.wallet_id = ?"
        params.append(wallet_id)
    if chain is not None:
        sql += " AND t.chain = ?"
        params.append(chain)
    direction = "DESC" if descending else "ASC"
    sql += """
        GROUP BY
            t.id, w.name, t.chain, t.timestamp, t.block_number, t.tx_hash,
            t.from_address, t.to_address, t.type, t.asset, t.contract_address,
            t.amount, t.source, t.method_id, t.method_name,
            tr.review_status, tr.review_reason
    """
    sql += f" ORDER BY t.timestamp {direction}, t.block_number {direction}, t.id {direction}"

    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _chain_label(chain: str) -> str:
    return CHAINS.get(chain, {}).get("label", chain)


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


def _table_df(rows: list[dict]) -> pd.DataFrame:
    display_rows = []
    for row in rows:
        display_rows.append({
            "Datum": _display_timestamp(row["timestamp"]),
            "Wallet": row["wallet"],
            "Chain": _chain_label(row["chain"]),
            "Type": _type_label(row["type"]),
            "Actie": _row_action_label(row),
            "Signaal": token_signal(row) or "-",
            "Bedrag": _display_amount(row["amount"]),
            "Asset": row["asset"],
            "Tx": short_tx_hash(row["tx_hash"]),
            "Bron": row["source"],
            "Explorer": explorer_tx_url(row["chain"], row["tx_hash"]),
        })
    return pd.DataFrame(display_rows, columns=TABLE_COLUMNS)


def _grouped_table_df(groups: list[dict]) -> pd.DataFrame:
    display_rows = []
    for group in groups:
        out_rows, in_rows, gas_rows = _split_group_rows(group["rows"])
        display_rows.append({
            "Datum": _display_timestamp(group["timestamp"]),
            "Wallet": group["wallet"],
            "Chain": _chain_label(group["chain"]),
            "Type": _group_type_label(group["type"]),
            "Actie": _group_action_label(group),
            "Signaal": ", ".join(group["signals"]) or "-",
            "Uit": _summarize_rows(out_rows, absolute=True),
            "In": _summarize_rows(in_rows, absolute=True),
            "Gas": _summarize_rows(gas_rows, absolute=True),
            "Tx": short_tx_hash(group["tx_hash"]),
            "Bron": ", ".join(group["sources"]),
            "Explorer": explorer_tx_url(group["chain"], group["tx_hash"]),
        })
    return pd.DataFrame(display_rows, columns=GROUPED_TABLE_COLUMNS)


def _csv_df(rows: list[dict]) -> pd.DataFrame:
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
            "tx_hash": row["tx_hash"],
            "normalized_tx_hash": normalized,
            "source": row["source"],
            "explorer_url": explorer_tx_url(row["chain"], row["tx_hash"]),
        })
    return pd.DataFrame(csv_rows, columns=CSV_COLUMNS)


def _grouped_csv_df(groups: list[dict]) -> pd.DataFrame:
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
            "assets": ", ".join(group["assets"]),
            "tx_hash": group["tx_hash"],
            "source": ", ".join(group["sources"]),
            "booking_rows": group["row_count"],
            "explorer_url": explorer_tx_url(group["chain"], group["tx_hash"]),
        })
    return pd.DataFrame(csv_rows, columns=GROUPED_CSV_COLUMNS)


wallets = _get_wallets()

if not wallets:
    st.info("Nog geen EVM wallets. Voeg ze toe via **EVM wallets**.")
    st.stop()

wallet_options = ["Alle wallets"] + [w["name"] for w in wallets]

col_wallet, col_chain, col_asset, col_view, col_sort = st.columns([2, 2, 2, 1.6, 1.4])

wallet_label = col_wallet.selectbox("Wallet", wallet_options, key="tx_wallet")
wallet_id = None if wallet_label == "Alle wallets" else next(
    w["id"] for w in wallets if w["name"] == wallet_label
)

chains = _get_chains(wallet_id)
chain_label_to_key = {_chain_label(chain): chain for chain in chains}
chain_options = ["Alle chains"] + list(chain_label_to_key.keys())
selected_chain_label = col_chain.selectbox("Chain", chain_options, key="tx_chain")
selected_chain = None if selected_chain_label == "Alle chains" else chain_label_to_key[selected_chain_label]

assets = _get_assets(wallet_id, selected_chain)
asset_options = ["Alle tokens"] + assets
asset_label = col_asset.selectbox("Token", asset_options, key="tx_asset")
selected_asset = None if asset_label == "Alle tokens" else asset_label

sort_label = col_sort.selectbox(
    "Sortering",
    ["Nieuwste eerst", "Oudste eerst"],
    key="tx_sort",
)
descending = sort_label == "Nieuwste eerst"

view_label = col_view.selectbox(
    "Weergave",
    ["Transacties", "Boekingsregels"],
    key="tx_view",
)

all_rows = _get_transactions(wallet_id, selected_chain, descending)
raw_rows = [row for row in all_rows if selected_asset is None or row["asset"] == selected_asset]
groups = logical_tx_groups(all_rows, selected_asset)

if view_label == "Boekingsregels":
    table_df = _table_df(raw_rows)
    csv_df = _csv_df(raw_rows)
    visible_count = len(raw_rows)
else:
    table_df = _grouped_table_df(groups)
    csv_df = _grouped_csv_df(groups)
    visible_count = len(groups)

c1, c2, c3 = st.columns(3)
c1.metric(view_label, visible_count)
c2.metric("Boekingsregels", sum(group["row_count"] for group in groups) if view_label == "Transacties" else len(raw_rows))
visible_assets = (
    {asset for group in groups for asset in group["assets"]}
    if view_label == "Transacties"
    else {r["asset"] for r in raw_rows}
)
c3.metric("Tokens", len(visible_assets))

download_name = csv_filename(wallet_label, selected_chain_label, asset_label)
col_download, col_backfill = st.columns([1, 1])
col_download.download_button(
    "Download CSV",
    data=csv_df.to_csv(index=False).encode("utf-8"),
    file_name=download_name,
    mime="text/csv",
    key="tx_csv_download",
    disabled=False,
)

if col_backfill.button(
    "Acties aanvullen",
    key="tx_method_backfill",
    help="Haalt method/action metadata op voor bestaande txlist-rijen. Verandert geen transacties of balansen.",
):
    progress = st.progress(0, text="Acties ophalen...")
    summary = backfill_transaction_methods(
        wallet_id=wallet_id,
        chain=selected_chain,
        progress_fn=lambda f, t: progress.progress(min(f, 0.99), text=t),
    )
    progress.progress(1.0, text="Klaar")
    if summary.errors:
        for error in summary.errors:
            st.warning(error)
    st.success(f"Acties aangevuld: {summary.updated} rij(en) bijgewerkt uit {summary.scanned} txlist-records.")
    st.rerun()

if visible_count:
    st.dataframe(
        table_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Datum": st.column_config.TextColumn("Datum"),
            "Wallet": st.column_config.TextColumn("Wallet"),
            "Chain": st.column_config.TextColumn("Chain"),
            "Type": st.column_config.TextColumn("Type"),
            "Actie": st.column_config.TextColumn("Actie"),
            "Signaal": st.column_config.TextColumn("Signaal"),
            "Bedrag": st.column_config.TextColumn("Bedrag"),
            "Uit": st.column_config.TextColumn("Uit"),
            "In": st.column_config.TextColumn("In"),
            "Gas": st.column_config.TextColumn("Gas"),
            "Asset": st.column_config.TextColumn("Asset"),
            "Tx": st.column_config.TextColumn("Tx"),
            "Bron": st.column_config.TextColumn("Bron"),
            "Explorer": st.column_config.LinkColumn("Explorer", display_text="Open"),
        },
    )
else:
    st.info("Geen transacties gevonden voor deze filters.")
    st.dataframe(
        table_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Explorer": st.column_config.LinkColumn("Explorer", display_text="Open"),
        },
    )
