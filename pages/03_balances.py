from decimal import Decimal

import streamlit as st
import pandas as pd

from core.db import get_connection
from core.models import CHAINS, format_token, BRIDGE_OUT, BRIDGE_IN
from core.balance_check import verify_balances
from core.token_review import sync_staking_wrappers, token_review_join_condition

st.title("Balansen")
st.caption("Som van alle transacties per token per wallet. Alleen tokens waarvoor 'Importeren' aangevinkt is.")

ZERO_THRESHOLD = Decimal("0.000001")

# Ensure staked wrapper tokens (xOPN, stPEAR) are accepted when their underlying is.
sync_staking_wrappers()


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
        sql = f"""
            SELECT
                w.name  AS wallet,
                t.chain,
                t.asset,
                t.amount
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            JOIN token_review tr
              ON {token_review_join_condition("t", "tr")}
            WHERE tr.accepted = 1
        """
        params: list = []
        if wallet_id is not None:
            sql += " AND t.wallet_id = ?"
            params.append(wallet_id)

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    totals: dict[tuple, Decimal] = {}
    for r in rows:
        key = (r["wallet"], r["chain"], r["asset"])
        totals[key] = totals.get(key, Decimal("0")) + Decimal(r["amount"])

    return [
        {"wallet": k[0], "chain": k[1], "asset": k[2], "balance": v}
        for k, v in sorted(totals.items())
    ]


def _get_bridge_summary(wallet_id: int | None = None) -> dict[tuple, dict]:
    conn = get_connection()
    try:
        sql = f"""
            SELECT w.name AS wallet, t.chain, t.asset, t.type, t.amount
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            JOIN token_review tr
              ON {token_review_join_condition("t", "tr")}
            WHERE t.type IN (?, ?)
              AND tr.accepted = 1
        """
        params: list = [BRIDGE_OUT, BRIDGE_IN]
        if wallet_id is not None:
            sql += " AND t.wallet_id = ?"
            params.append(wallet_id)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    summary: dict[tuple, dict] = {}
    for r in rows:
        key = (r["wallet"], r["chain"], r["asset"])
        entry = summary.setdefault(key, {"out": Decimal("0"), "in": Decimal("0"), "count": 0})
        amt = Decimal(r["amount"])
        if r["type"] == BRIDGE_OUT:
            entry["out"] += amt
        else:
            entry["in"] += amt
        entry["count"] += 1
    return summary


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

wallets = _get_wallets()

if not wallets:
    st.info("Nog geen wallets. Voeg ze toe via **Wallets**.")
    st.stop()

col_sel, col_toggle = st.columns([3, 1])
options = ["Alle wallets"] + [w["name"] for w in wallets]
selected_label = col_sel.selectbox("Wallet", options, key="bal_wallet_sel")
selected_id = None if selected_label == "Alle wallets" else next(
    w["id"] for w in wallets if w["name"] == selected_label
)
hide_zero = col_toggle.checkbox("Verberg nullen", value=True, key="hide_zero")

balances      = _get_balances(selected_id)
bridge_summary = _get_bridge_summary(selected_id)

if not balances:
    st.info("Geen balansen gevonden. Haal transacties op via **Importeren** en vink tokens aan.")
    st.stop()

# Build display rows
rows = []
negatives = 0
bridge_explained = 0

for b in balances:
    bal = b["balance"]

    if abs(bal) < ZERO_THRESHOLD:
        bal = Decimal("0")
    is_neg = bal < 0

    bridged_out    = Decimal("0")
    is_bridge_caused = False
    if is_neg:
        negatives += 1
        key = (b["wallet"], b["chain"], b["asset"])
        br = bridge_summary.get(key)
        if br:
            bridged_out = -br["out"]
            if bridged_out >= -bal - ZERO_THRESHOLD:
                is_bridge_caused = True
                bridge_explained += 1

    rows.append({
        "":       "🌉" if is_bridge_caused else ("⚠️" if is_neg else ""),
        "Wallet": b["wallet"],
        "Chain":  CHAINS.get(b["chain"], {}).get("label", b["chain"]),
        "Token":  b["asset"],
        "Balans": format_token(bal),
        "_zero":  bal == 0,
        "_neg":   is_neg,
        "_bridge": is_bridge_caused,
    })

if hide_zero:
    rows = [r for r in rows if not r["_zero"]]

if negatives:
    if bridge_explained:
        unexplained = negatives - bridge_explained
        msg = (f"{negatives} token(s) met een negatieve balans — "
               f"waarvan {bridge_explained} verklaarbaar door bridge-uitgaande transfers (🌉)")
        if unexplained:
            msg += f", {unexplained} mogelijk door ontbrekende transacties (⚠️)"
        msg += "."
        st.warning(msg)
    else:
        st.warning(f"{negatives} token(s) met een negatieve balans — er ontbreken waarschijnlijk transacties.")

total_tokens = len(rows)
positive     = sum(1 for r in rows if not r["_neg"] and not r["_zero"])

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
        "🌉 = saldo negatief door bridge-uitgaande transfers.  "
        "⚠️ = negatief door ontbrekende transacties."
    )

# ---------------------------------------------------------------------------
# On-chain verificatie
# ---------------------------------------------------------------------------
st.divider()
st.subheader("On-chain verificatie")
st.caption(
    "Vergelijkt je gereconstrueerde saldi met de live balans op de chain. "
    "Een verschil (∆) duidt vaak op rebasing tokens (stETH, AMPL), fee-on-transfer, "
    "of ontbrekende transacties. Eén API-call per token — dus bij veel tokens "
    "duurt het even (≈5 calls/sec free tier)."
)

verify_clicked = st.button("Verifieer tegen on-chain", key="verify_btn")

if verify_clicked:
    progress = st.progress(0, text="Bezig...")
    try:
        check_rows = verify_balances(
            wallet_id=selected_id,
            progress_fn=lambda f, t: progress.progress(min(f, 0.99), text=t),
        )
        progress.progress(1.0, text="Klaar")
        st.session_state["balance_check"] = check_rows
    except Exception as e:
        progress.empty()
        st.error(f"Verificatie mislukt: {e}")

check_rows = st.session_state.get("balance_check")
if check_rows:
    if selected_id is not None:
        sel_name = next(w["name"] for w in wallets if w["id"] == selected_id)
        visible = [r for r in check_rows if r.wallet == sel_name]
    else:
        visible = list(check_rows)

    mismatches = 0
    errors_n   = 0
    unknown_dec = 0
    check_table = []
    for r in visible:
        if r.error:
            errors_n += 1
            delta_str   = "—"
            onchain_str = "—"
            symbol = "❌"
        elif not r.decimals_known:
            unknown_dec += 1
            delta_str   = "(decimals onbekend — re-fetch)"
            onchain_str = format_token(r.onchain, decimals=0)
            symbol = "❓"
        else:
            d = r.delta or Decimal("0")
            if abs(d) < ZERO_THRESHOLD:
                symbol    = "✅"
                delta_str = format_token(Decimal("0"))
            else:
                symbol = "⚠️"
                mismatches += 1
                delta_str = format_token(d)
            onchain_str = format_token(r.onchain)

        check_table.append({
            "":         symbol,
            "Wallet":   r.wallet,
            "Chain":    CHAINS.get(r.chain, {}).get("label", r.chain),
            "Token":    r.asset,
            "Computed": format_token(r.computed),
            "On-chain": onchain_str,
            "∆":        delta_str,
            "Detail":   r.error or "",
        })

    c1, c2, c3 = st.columns(3)
    c1.metric("✅ Match", len(visible) - mismatches - errors_n - unknown_dec)
    c2.metric("⚠️ Verschil", mismatches)
    c3.metric("❌ Fout / ❓ onbekend", errors_n + unknown_dec)

    st.dataframe(
        pd.DataFrame(check_table),
        hide_index=True,
        use_container_width=True,
    )
    st.caption(
        "✅ = saldo klopt  ·  ⚠️ = verschil tussen reconstructie en on-chain  ·  "
        "❓ = decimals nog onbekend (re-fetch om te populeren)  ·  "
        "❌ = API-call mislukt (zie Detail)"
    )

# ---------------------------------------------------------------------------
# Bridge activity expander
# ---------------------------------------------------------------------------
if bridge_summary:
    with st.expander(f"Bridge-activiteit ({len(bridge_summary)} regel(s))", expanded=False):
        bridge_rows = []
        for (w, ch, asset), agg in sorted(bridge_summary.items()):
            bridge_rows.append({
                "Wallet":              w,
                "Chain":               CHAINS.get(ch, {}).get("label", ch),
                "Token":               asset,
                "Uitgaand (bridge)":   format_token(-agg["out"]),
                "Inkomend (bridge)":   format_token(agg["in"]),
                "Aantal":              agg["count"],
            })
        st.dataframe(
            pd.DataFrame(bridge_rows),
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Bridge-uitgaande transfers gaan naar een ander netwerk. Als je dat netwerk ook "
            "importeert zie je daar de inkomende kant terug en is het netto saldo nul."
        )

# ---------------------------------------------------------------------------
# BEAM node staking
# ---------------------------------------------------------------------------
st.divider()
st.subheader("BEAM node staking")
st.caption(
    "Gestaked BEAM op de node staking contract. Live berekend via de BEAM chain API. "
    "Formule: Σ deposits naar contract − Σ withdrawals van contract."
)

if st.button("Laad BEAM staking saldo", key="beam_staking_btn"):
    from core.db import get_connection as _gc
    from core.staking import fetch_beam_staking_balance

    conn = _gc()
    beam_wallets = conn.execute(
        "SELECT id, name, address FROM wallets ORDER BY id"
    ).fetchall()
    conn.close()

    staking_rows = []
    for w in beam_wallets:
        bal = fetch_beam_staking_balance(w["address"])
        if bal is not None and abs(bal) > Decimal("1"):
            staking_rows.append({
                "Wallet": w["name"],
                "Chain": "BEAM",
                "Token": "BEAM (gestaked)",
                "Balans": format_token(bal),
            })

    if staking_rows:
        st.dataframe(pd.DataFrame(staking_rows), hide_index=True, use_container_width=True)
    else:
        st.info("Geen BEAM staking gevonden voor de bekende wallets.")
