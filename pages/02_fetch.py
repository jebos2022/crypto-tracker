import streamlit as st
import pandas as pd

from core.db import get_connection
from core.models import CHAINS
from core.fetcher import (
    fetch_all, get_unique_tokens, set_token_accepted_global,
    accept_all_tokens, auto_reject_scams, accept_non_scams, is_scam, looks_like_ticker,
)

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
    "Eén vinkje geldt voor **alle wallets** tegelijk. "
    "Scam-tokens worden automatisch herkend en verborgen."
)

all_tokens = get_unique_tokens()

if not all_tokens:
    if _inbox_count() > 0:
        st.info("Alle tokens zijn al ingesteld.")
    else:
        st.info("Nog geen transacties opgehaald. Klik op 'Haal alle transacties op' hierboven.")
else:
    # Split scam vs clean
    clean = [t for t in all_tokens if not is_scam(t["asset"])]
    scam  = [t for t in all_tokens if is_scam(t["asset"])]

    # Quick-action buttons
    c1, c2, c3, c4 = st.columns(4)

    if c1.button("Aanvinken excl. scams", use_container_width=True, key="accept_non_scams_btn", type="primary"):
        accepted, rejected = accept_non_scams()
        st.success(f"✅ {accepted} tokens aangevinkt, {rejected} scams afgewezen.")
        st.rerun()

    if c2.button("Scams afwijzen", use_container_width=True, key="reject_scams_btn"):
        n = auto_reject_scams()
        st.success(f"✅ {n} scam-entries afgewezen.")
        st.rerun()

    if c3.button("Alles aanvinken", use_container_width=True, key="accept_all_btn"):
        accept_all_tokens()
        st.success("✅ Alles geselecteerd.")
        st.rerun()

    if c4.button("Alles uitvinken", use_container_width=True, key="reject_all_btn"):
        from core.db import get_connection as _gc
        conn = _gc()
        conn.execute("UPDATE token_review SET accepted = 0")
        conn.commit()
        conn.close()
        st.success("✅ Alles uitgevinkt.")
        st.rerun()

    # Stats
    n_accepted = sum(1 for t in clean if t["accepted"])
    n_scam_hidden = len(scam)
    st.caption(
        f"{n_accepted} van {len(clean)} tokens aangevinkt  ·  "
        f"{n_scam_hidden} scam-tokens verborgen"
    )

    if not clean:
        st.info("Geen tokens gevonden na scam-filter.")
    else:
        # Build editable table — one row per unique (chain, asset)
        df = pd.DataFrame([{
            "Chain":      t["chain"],
            "Token":      t["asset"],
            "Wallets":    t["wallet_count"],
            "Importeren": bool(t["accepted"]),
        } for t in clean])

        edited = st.data_editor(
            df,
            column_config={
                "Chain":      st.column_config.TextColumn("Chain",   disabled=True),
                "Token":      st.column_config.TextColumn("Token",   disabled=True),
                "Wallets":    st.column_config.NumberColumn("Wallets", disabled=True, width="small"),
                "Importeren": st.column_config.CheckboxColumn("Importeren"),
            },
            hide_index=True,
            use_container_width=True,
            key="token_editor",
        )

        if st.button("Selectie opslaan", type="primary", use_container_width=True, key="save_sel_btn"):
            for i, t in enumerate(clean):
                new_val = bool(edited.iloc[i]["Importeren"])
                set_token_accepted_global(t["chain"], t["asset"], new_val)
            accepted = int(edited["Importeren"].sum())
            st.success(f"✅ Opgeslagen — {accepted} token(s) geselecteerd.")
            st.rerun()

    if scam:
        with st.expander(f"Verborgen scam-tokens ({len(scam)})", expanded=False):
            st.dataframe(
                pd.DataFrame([{"Chain": t["chain"], "Token": t["asset"]} for t in scam]),
                hide_index=True,
                use_container_width=True,
            )
