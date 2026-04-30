import streamlit as st
import pandas as pd

from core.db import get_connection
from core.models import CHAINS
from core.fetcher import fetch_all
from core.ledger import explorer_tx_url, normalize_tx_hash
from core.token_review import (
    get_unique_tokens, save_token_selection_global,
    accept_recommended_tokens, auto_reject_scams, reject_all_tokens,
    get_recent_token_transactions,
    enrich_tokens, count_enrichable_contracts,
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
    st.warning("Geen EVM wallets gevonden. Voeg eerst wallets toe via **EVM wallets**.")
    st.stop()

st.subheader("1. EVM wallets")
st.caption(f"{len(wallets)} EVM wallet(s) — {', '.join(CHAINS.keys())} worden gecheckt.")
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
    "Alle transacties blijven bewaard; alleen geaccepteerde tokens gaan mee naar balansen, ledger en export."
)

all_tokens = get_unique_tokens()

if not all_tokens:
    if _inbox_count() > 0:
        st.info("Alle tokens zijn al ingesteld.")
    else:
        st.info("Nog geen transacties opgehaald. Klik op 'Haal alle transacties op' hierboven.")
else:
    n_contracts = count_enrichable_contracts()
    n_enriched = sum(1 for t in all_tokens if t.get("has_metadata"))
    enrich_col, enrich_status = st.columns([2, 3])
    if enrich_col.button(
        f"Metadata ophalen ({n_contracts} tokens)",
        key="enrich_btn",
        use_container_width=True,
        help="Haalt verificatie, houders en social info op via Etherscan. Duurt ~30 sec.",
    ):
        prog = st.progress(0, text="Metadata ophalen…")
        enriched, failed = enrich_tokens(
            progress_fn=lambda f, t: prog.progress(min(f, 0.99), text=t)
        )
        prog.progress(1.0, text="Klaar")
        st.success(f"✅ {enriched} tokens verrijkt, {failed} niet beschikbaar.")
        st.rerun()
    if n_enriched:
        enrich_status.caption(f"{n_enriched} van {n_contracts} tokens hebben metadata.")

    c1, c2, c3 = st.columns(3)
    if c1.button("Aanbevolen accepteren", use_container_width=True, key="accept_recommended_btn", type="primary"):
        accepted, rejected = accept_recommended_tokens()
        st.success(f"✅ {accepted} zeker-goed token(s) geaccepteerd, {rejected} onbekend/verdacht/scam afgewezen.")
        st.rerun()

    if c2.button("Scams afwijzen", use_container_width=True, key="reject_scams_btn"):
        n = auto_reject_scams()
        st.success(f"✅ {n} scam-entries afgewezen.")
        st.rerun()

    if c3.button("Alles uitvinken", use_container_width=True, key="reject_all_btn"):
        reject_all_tokens()
        st.success("✅ Alles uitgevinkt.")
        st.rerun()

    def _contract_label(contract: str | None) -> str:
        if not contract:
            return "native"
        return f"{contract[:10]}…{contract[-6:]}"

    def _status_label(status: str) -> str:
        return {
            "safe": "Zeker goed",
            "unknown": "Onbekend",
            "suspicious": "Verdacht",
            "scam": "Scam",
        }.get(status, status)

    def _token_df(tokens: list[dict]) -> pd.DataFrame:
        return pd.DataFrame([{
            "Status": _status_label(t["review_status"]),
            "Chain": t["chain"],
            "Token": t["asset"],
            "Contract": _contract_label(t.get("contract_address")),
            "Reden": t.get("review_reason") or "",
            "Houders": t["holder_count"] if t.get("holder_count") is not None else "—",
            "Wallets": t["wallet_count"],
            "Bron": "handmatig" if t.get("decision_source") == "user" else "auto",
            "Importeren": bool(t["accepted"]),
        } for t in tokens])

    def _tx_context_df(token: dict) -> pd.DataFrame:
        rows = []
        for row in get_recent_token_transactions(token["chain"], token["token_key"], limit=5):
            rows.append({
                "Datum": row["timestamp"].replace("T", " ")[:19],
                "Wallet": row["wallet"],
                "Bedrag": row["amount"],
                "Asset": row["asset"],
                "Contract": _contract_label(row.get("contract_address")),
                "Tx": normalize_tx_hash(row["tx_hash"])[:12] + "…",
                "Bron": row["source"],
                "Explorer": explorer_tx_url(token["chain"], row["tx_hash"]),
            })
        return pd.DataFrame(rows)

    groups = {
        "safe": [t for t in all_tokens if t["review_status"] == "safe"],
        "unknown": [t for t in all_tokens if t["review_status"] == "unknown"],
        "suspicious": [t for t in all_tokens if t["review_status"] == "suspicious"],
        "scam": [t for t in all_tokens if t["review_status"] == "scam"],
    }

    n_accepted = sum(1 for t in all_tokens if t["accepted"])
    st.caption(
        f"{n_accepted} van {len(all_tokens)} tokens geïmporteerd  ·  "
        f"{len(groups['safe'])} zeker goed  ·  "
        f"{len(groups['unknown'])} onbekend  ·  "
        f"{len(groups['suspicious'])} verdacht  ·  "
        f"{len(groups['scam'])} scam"
    )

    group_titles = {
        "safe": "Zeker goed",
        "unknown": "Onbekend — zelf controleren",
        "suspicious": "Verdacht — metadata-signaal",
        "scam": "Scam — naam/signaal",
    }

    for status in ("safe", "unknown", "suspicious", "scam"):
        tokens = groups[status]
        if not tokens:
            continue
        expanded = status in {"safe", "unknown"}
        with st.expander(f"{group_titles[status]} ({len(tokens)})", expanded=expanded):
            edited = st.data_editor(
                _token_df(tokens),
                column_config={
                    "Status": st.column_config.TextColumn("Status", disabled=True),
                    "Chain": st.column_config.TextColumn("Chain", disabled=True),
                    "Token": st.column_config.TextColumn("Token", disabled=True),
                    "Contract": st.column_config.TextColumn("Contract", disabled=True),
                    "Reden": st.column_config.TextColumn("Reden", disabled=True),
                    "Houders": st.column_config.TextColumn("Houders", disabled=True, width="small"),
                    "Wallets": st.column_config.NumberColumn("Wallets", disabled=True, width="small"),
                    "Bron": st.column_config.TextColumn("Bron", disabled=True, width="small"),
                    "Importeren": st.column_config.CheckboxColumn("Importeren"),
                },
                hide_index=True,
                use_container_width=True,
                key=f"{status}_editor",
            )

            if st.button("Selectie opslaan", key=f"save_{status}_btn"):
                save_token_selection_global([
                    (t["chain"], t["token_key"], bool(edited.iloc[i]["Importeren"]))
                    for i, t in enumerate(tokens)
                ])
                st.success("✅ Opgeslagen.")
                st.rerun()

            if status != "safe":
                st.caption("Laatste transacties per token, zodat je de herkomst snel kunt openen.")
                for t in tokens:
                    st.markdown(f"**{t['asset']}** · `{_contract_label(t.get('contract_address'))}` · {t.get('review_reason')}")
                    tx_df = _tx_context_df(t)
                    if tx_df.empty:
                        st.caption("Geen transacties gevonden.")
                    else:
                        st.dataframe(
                            tx_df,
                            hide_index=True,
                            use_container_width=True,
                            column_config={
                                "Explorer": st.column_config.LinkColumn("Explorer", display_text="Open"),
                            },
                        )
