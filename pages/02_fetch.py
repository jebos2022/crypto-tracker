import os

import streamlit as st

from core.db import clear_transactions, transaction_count
from core.env import load_env
from core.fetcher import fetch_all
from core.models import CHAINS
from core.token_review import get_unique_tokens
from core.wallets import get_wallets_for_fetch
from ui.styles import apply_design_system
from ui.token_intake import render_token_intake

apply_design_system()

st.title("Importeren")
st.caption("Haal on-chain transacties op via de Etherscan en Routescan API.")
load_env()


# ---------------------------------------------------------------------------
# Step 1 — Fetch
# ---------------------------------------------------------------------------

wallets = get_wallets_for_fetch()

if not wallets:
    st.warning("Geen EVM wallets gevonden. Voeg eerst wallets toe via **EVM wallets**.")
    st.stop()

st.subheader("1. EVM wallets")
st.caption(f"{len(wallets)} EVM wallet(s) — {', '.join(CHAINS.keys())} worden gecheckt.")
for wallet in wallets:
    st.caption(f"• **{wallet['name']}** — `{wallet['address']}`")

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
        clear_transactions()
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
        for error in summary.errors:
            st.warning(f"⚠️ {error}")

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
st.subheader("3. Begeleide token-intake")
st.caption(
    "Eén vinkje geldt voor **alle wallets** tegelijk. "
    "Alle transacties blijven bewaard; alleen geaccepteerde tokens gaan mee naar balansen, ledger en export. "
    "De intake zet zekere tokens klaar voor import, duidelijke scams apart, en houdt een korte twijfel-lijst over."
)

all_tokens = get_unique_tokens()

if not all_tokens:
    if transaction_count() > 0:
        st.info("Alle tokens zijn al ingesteld.")
    else:
        st.info("Nog geen transacties opgehaald. Klik op 'Haal alle transacties op' hierboven.")
else:
    render_token_intake(all_tokens)
