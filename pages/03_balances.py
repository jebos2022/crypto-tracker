from decimal import Decimal

import streamlit as st
import pandas as pd

from core.db import get_connection
from core.models import CHAINS, format_token

st.title("Balansen")
st.caption("Som van alle transacties per token per wallet. Alleen tokens waarvoor 'Importeren' aangevinkt is.")

# Bedragen kleiner dan dit worden als nul beschouwd (float-afrondingsruis)
ZERO_THRESHOLD = Decimal("0.000001")


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def _get_wallets() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, name FROM wallets ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_balances(wallet_id: int | None = None) -> list[dict]:
    """Fetch raw transaction rows and sum in Python with Decimal for precision."""
    conn = get_connection()
    try:
        sql = """
            SELECT
                w.name  AS wallet,
                t.chain,
                t.asset,
                t.amount
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            JOIN token_review tr
              ON tr.wallet_id = t.wallet_id
             AND tr.chain     = t.chain
             AND tr.asset     = t.asset
            WHERE tr.accepted = 1
        """
        params: list = []
        if wallet_id is not None:
            sql += " AND t.wallet_id = ?"
            params.append(wallet_id)

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    # Sum per (wallet, chain, asset) using Decimal
    totals: dict[tuple, Decimal] = {}
    for r in rows:
        key = (r["wallet"], r["chain"], r["asset"])
        totals[key] = totals.get(key, Decimal("0")) + Decimal(r["amount"])

    return [
        {"wallet": k[0], "chain": k[1], "asset": k[2], "balance": v}
        for k, v in sorted(totals.items())
    ]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

wallets = _get_wallets()

if not wallets:
    st.info("Nog geen wallets. Voeg ze toe via **Wallets**.")
    st.stop()

# Filters
col_sel, col_toggle = st.columns([3, 1])
options = ["Alle wallets"] + [w["name"] for w in wallets]
selected_label = col_sel.selectbox("Wallet", options, key="bal_wallet_sel")
selected_id = None if selected_label == "Alle wallets" else next(
    w["id"] for w in wallets if w["name"] == selected_label
)
hide_zero = col_toggle.checkbox("Verberg nullen", value=True, key="hide_zero")

balances = _get_balances(selected_id)

if not balances:
    st.info("Geen balansen gevonden. Haal transacties op via **Importeren** en vink tokens aan.")
    st.stop()

# Build display rows
rows = []
negatives = 0
for b in balances:
    bal = b["balance"]
    # Treat near-zero as exactly zero (floating-point rounding noise)
    if abs(bal) < ZERO_THRESHOLD:
        bal = Decimal("0")
    is_neg = bal < 0
    if is_neg:
        negatives += 1
    rows.append({
        "":       "⚠️" if is_neg else "",
        "Wallet": b["wallet"],
        "Chain":  CHAINS.get(b["chain"], {}).get("label", b["chain"]),
        "Token":  b["asset"],
        "Balans": format_token(bal),
        "_zero":  bal == 0,
        "_neg":   is_neg,
    })

if hide_zero:
    rows = [r for r in rows if not r["_zero"]]

if negatives:
    st.warning(f"{negatives} token(s) met een negatieve balans — er ontbreken waarschijnlijk transacties.")

total_tokens = len(rows)
positive = sum(1 for r in rows if not r["_neg"] and not r["_zero"])

c1, c2, c3 = st.columns(3)
c1.metric("Tokens", total_tokens)
c2.metric("Positief saldo", positive)
c3.metric("⚠️ Negatief", negatives)

st.divider()

display_df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "":       st.column_config.TextColumn("", width="small"),
        "Wallet": st.column_config.TextColumn("Wallet"),
        "Chain":  st.column_config.TextColumn("Chain"),
        "Token":  st.column_config.TextColumn("Token"),
        "Balans": st.column_config.TextColumn("Balans"),
    },
)

if negatives:
    st.caption(
        "⚠️ Negatieve balans betekent dat er meer uitstromen dan instromen geregistreerd zijn. "
        "Mogelijke oorzaken: onvolledige import (ontbrekende chains of wallets) of transacties "
        "die nog buiten scope vallen (bijv. CEX-transfers)."
    )
