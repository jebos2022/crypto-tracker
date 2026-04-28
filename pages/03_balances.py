from decimal import Decimal

import streamlit as st
import pandas as pd

from core.db import get_connection
from core.models import CHAINS, format_token

st.title("Balansen")
st.caption("Som van alle transacties per token per wallet. Alleen tokens waarvoor 'Importeren' aangevinkt is.")


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
    conn = get_connection()
    try:
        base_sql = """
            SELECT
                w.name       AS wallet,
                t.chain,
                t.asset,
                SUM(CAST(t.amount AS REAL)) AS balance
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
            base_sql += " AND t.wallet_id = ?"
            params.append(wallet_id)

        base_sql += " GROUP BY t.wallet_id, t.chain, t.asset ORDER BY w.name, t.chain, t.asset"

        rows = conn.execute(base_sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

wallets = _get_wallets()

if not wallets:
    st.info("Nog geen wallets. Voeg ze toe via **Wallets**.")
    st.stop()

# Wallet filter
options = ["Alle wallets"] + [w["name"] for w in wallets]
selected_label = st.selectbox("Wallet", options, key="bal_wallet_sel")
selected_id = None if selected_label == "Alle wallets" else next(
    w["id"] for w in wallets if w["name"] == selected_label
)

balances = _get_balances(selected_id)

if not balances:
    st.info("Geen balansen gevonden. Haal transacties op via **Importeren** en vink tokens aan.")
    st.stop()

# Build display rows
rows = []
negatives = 0
for b in balances:
    bal = Decimal(str(b["balance"] or "0"))
    is_neg = bal < 0
    if is_neg:
        negatives += 1
    rows.append({
        "":        "⚠️" if is_neg else "",
        "Wallet":  b["wallet"],
        "Chain":   CHAINS.get(b["chain"], {}).get("label", b["chain"]),
        "Token":   b["asset"],
        "Balans":  format_token(bal),
        "_neg":    is_neg,
    })

if negatives:
    st.warning(f"{negatives} token(s) met een negatieve balans — er ontbreken waarschijnlijk transacties.")

# Summary metrics
total_tokens = len(rows)
positive = total_tokens - negatives

c1, c2, c3 = st.columns(3)
c1.metric("Tokens", total_tokens)
c2.metric("Positief", positive)
c3.metric("⚠️ Negatief", negatives)

st.divider()

# Render table — highlight negatives
display_df = pd.DataFrame([{k: v for k, v in r.items() if k != "_neg"} for r in rows])

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
