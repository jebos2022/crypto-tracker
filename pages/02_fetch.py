import streamlit as st
import pandas as pd

from core.db import get_connection
from core.models import CHAINS
from core.fetcher import fetch_all, get_pending_tokens, set_token_accepted, accept_all_tokens

st.title("Importeren")
st.caption("Haal on-chain transacties op via de Etherscan en Routescan API.")


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_wallets() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, address FROM wallets ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _inbox_count() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def _reset_inbox() -> None:
    conn = get_connection()
    try:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM wallet_chain_state")
        conn.execute("DELETE FROM token_review")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Step 1 — Fetch
# ---------------------------------------------------------------------------

wallets = _get_wallets()

if not wallets:
    st.warning("Geen wallets gevonden. Voeg eerst wallets toe via **Wallets**.")
    st.stop()

st.subheader("1. Wallets")
st.caption(f"{len(wallets)} wallet(s) — {', '.join(CHAINS.keys())} worden gecheckt.")
for w in wallets:
    st.caption(f"• **{w['name']}** — `{w['address']}`")

# API key check
import os
eth_key = os.getenv("ETHERSCAN_API_KEY", "")
if not eth_key:
    st.error("ETHERSCAN_API_KEY niet gevonden in `.env`. Zet de key in `.env` en herstart de app.")
    st.stop()

st.divider()
st.subheader("2. Ophalen")

col_fetch, col_reset = st.columns([3, 1])

fetch_clicked = col_fetch.button(
    "Haal alle transacties op",
    type="primary",
    key="fetch_btn",
    use_container_width=True,
)

if col_reset.button("Alles wissen", key="reset_btn", use_container_width=True):
    st.session_state["confirm_reset"] = True

if st.session_state.get("confirm_reset"):
    st.warning("Dit verwijdert **alle** transacties, fetch-status en token-instellingen. Weet je het zeker?")
    c1, c2 = st.columns(2)
    if c1.button("Ja, alles wissen", type="primary", key="confirm_reset_yes"):
        _reset_inbox()
        st.session_state.pop("confirm_reset", None)
        st.session_state.pop("fetch_summary", None)
        st.success("✅ Alles gewist.")
        st.rerun()
    if c2.button("Annuleren", key="confirm_reset_no"):
        st.session_state.pop("confirm_reset", None)
        st.rerun()

if fetch_clicked:
    progress = st.progress(0, text="Bezig...")
    summary = fetch_all(
        wallets,
        progress_fn=lambda f, t: progress.progress(min(f, 0.99), text=t),
    )
    progress.progress(1.0, text="Klaar")
    st.session_state["fetch_summary"] = summary

    if summary.errors:
        for err in summary.errors:
            st.warning(f"⚠️ {err}")

    st.rerun()

summary = st.session_state.get("fetch_summary")
if summary:
    c1, c2 = st.columns(2)
    c1.metric("Nieuwe transacties", summary.total_new)
    c2.metric("Overgeslagen (al bekend)", summary.total_skipped)

    if summary.total_new == 0 and summary.total_skipped == 0:
        st.info("Geen nieuwe transacties gevonden op de chain.")

# ---------------------------------------------------------------------------
# Step 2 — Token review
# ---------------------------------------------------------------------------

st.divider()
st.subheader("3. Token review")
st.caption(
    "Vink de tokens aan die je wilt importeren. Nieuwe tokens staan standaard **UIT** — "
    "zo filter je automatisch scam/spam-tokens."
)

token_rows = get_pending_tokens()

if not token_rows:
    total = _inbox_count()
    if total > 0:
        st.info(f"Alle {total} transacties staan al ingesteld. Pas eventueel de selectie hieronder aan.")
    else:
        st.info("Nog geen transacties opgehaald. Klik op 'Haal alle transacties op' hierboven.")
    token_rows = get_pending_tokens()

if token_rows:
    # Build editable dataframe
    df = pd.DataFrame([{
        "Wallet":    r["wallet_name"],
        "Chain":     r["chain"],
        "Token":     r["asset"],
        "Importeren": bool(r["accepted"]),
    } for r in token_rows])

    edited = st.data_editor(
        df,
        column_config={
            "Wallet":     st.column_config.TextColumn(disabled=True),
            "Chain":      st.column_config.TextColumn(disabled=True),
            "Token":      st.column_config.TextColumn(disabled=True),
            "Importeren": st.column_config.CheckboxColumn("Importeren"),
        },
        hide_index=True,
        use_container_width=True,
        key="token_editor",
    )

    col_save, col_all = st.columns([2, 1])

    if col_save.button("Selectie opslaan", type="primary", use_container_width=True, key="save_sel_btn"):
        for i, row in enumerate(token_rows):
            new_val = bool(edited.iloc[i]["Importeren"])
            set_token_accepted(row["wallet_id"], row["chain"], row["asset"], new_val)
        accepted = int(edited["Importeren"].sum())
        st.success(f"✅ Opgeslagen — {accepted} token(s) geselecteerd.")
        st.rerun()

    if col_all.button("Alles selecteren", use_container_width=True, key="accept_all_btn"):
        accept_all_tokens()
        st.success("✅ Alle tokens geselecteerd.")
        st.rerun()

    selected_count = int(df["Importeren"].sum())
    total_count = len(df)
    st.caption(f"{selected_count} van {total_count} tokens geselecteerd.")
