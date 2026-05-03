import streamlit as st
import pandas as pd

from core.db import get_connection
from core.models import CHAINS
from core.fetcher import fetch_all
from core.ledger import explorer_address_url, explorer_tx_url, normalize_tx_hash
from core.token_review import (
    get_unique_tokens, save_token_selection_global,
    accept_recommended_tokens, auto_reject_scams, reject_all_tokens,
    get_recent_token_transactions,
    enrich_tokens, count_enrichable_contracts,
    enrich_public_sources, count_public_enrichable_contracts,
    token_intake_guidance, token_intake_sort_key,
    INTAKE_HIDDEN, INTAKE_IMPORT, INTAKE_NOISE, INTAKE_REVIEW,
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
st.subheader("3. Begeleide token-intake")
st.caption(
    "Eén vinkje geldt voor **alle wallets** tegelijk. "
    "Alle transacties blijven bewaard; alleen geaccepteerde tokens gaan mee naar balansen, ledger en export. "
    "De intake zet zekere tokens klaar voor import, duidelijke scams apart, en houdt een korte twijfel-lijst over."
)

all_tokens = get_unique_tokens()

if not all_tokens:
    if _inbox_count() > 0:
        st.info("Alle tokens zijn al ingesteld.")
    else:
        st.info("Nog geen transacties opgehaald. Klik op 'Haal alle transacties op' hierboven.")
else:
    n_contracts = count_enrichable_contracts()
    n_public_contracts = count_public_enrichable_contracts()
    n_enriched = sum(1 for t in all_tokens if t.get("has_metadata"))
    intake_col, public_col, enrich_col, enrich_status = st.columns([2, 2, 2, 3])
    if intake_col.button(
        "Automatische intake draaien",
        key="auto_intake_btn",
        use_container_width=True,
        type="primary",
        help="Haalt publieke bronnen en metadata op, accepteert zekere tokens en laat onbekend/verdacht/scam uitgevinkt.",
    ):
        public_prog = st.progress(0, text="Publieke bronnen ophalen...")
        public_updated, public_failed = enrich_public_sources(
            progress_fn=lambda f, t: public_prog.progress(min(f, 0.99), text=t)
        )
        public_prog.progress(1.0, text="Publieke bronnen klaar")

        meta_prog = st.progress(0, text="Metadata ophalen...")
        metadata_updated, metadata_failed = enrich_tokens(
            progress_fn=lambda f, t: meta_prog.progress(min(f, 0.99), text=t)
        )
        meta_prog.progress(1.0, text="Metadata klaar")

        accepted, rejected = accept_recommended_tokens()
        st.success(
            "✅ Intake klaar: "
            f"{accepted} zeker-goed token(s) aangevinkt, {rejected} token(s) verborgen of ter review gelaten. "
            f"Publieke signalen: {public_updated} bijgewerkt/{public_failed} fout(en). "
            f"Metadata: {metadata_updated} bijgewerkt/{metadata_failed} fout(en)."
        )
        st.rerun()

    if public_col.button(
        f"Publieke check ({n_public_contracts} tokens)",
        key="public_enrich_btn",
        use_container_width=True,
        help="Checkt CoinGecko token lists, CoinGecko contract lookup en GoPlus security. Resultaten worden gecachet.",
    ):
        prog = st.progress(0, text="Publieke bronnen ophalen...")
        updated, failed = enrich_public_sources(
            progress_fn=lambda f, t: prog.progress(min(f, 0.99), text=t)
        )
        prog.progress(1.0, text="Klaar")
        st.success(f"✅ {updated} publieke signalen bijgewerkt, {failed} fout(en).")
        st.rerun()
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
    if c1.button("Voorstel toepassen", use_container_width=True, key="accept_recommended_btn"):
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

    def _unknown_hint(token: dict) -> str:
        in_count = int(token.get("in_count") or 0)
        out_count = int(token.get("out_count") or 0)
        tx_count = int(token.get("tx_count") or 0)
        self_swap_count = int(token.get("self_initiated_swap_count") or 0)
        bulk_airdrop_count = int(token.get("bulk_airdrop_count") or 0)
        if token["review_status"] == "safe":
            return ""
        if tx_count == 0:
            return "Geen transacties"
        if self_swap_count > 0:
            return "Eigen DEX-swap"
        if bulk_airdrop_count > 0:
            return "Bulk-airdrop"
        if in_count > 0 and out_count == 0:
            return "Alleen inkomend"
        if out_count > 0:
            return "Eigen activiteit"
        return "Onbekend patroon"

    def _net_label(token: dict) -> str:
        value = token.get("net_amount")
        if value is None:
            return "-"
        try:
            return f"{float(value):,.8g}".replace(",", "X").replace(".", ",").replace("X", ".")
        except (TypeError, ValueError):
            return "-"

    def _token_df(tokens: list[dict]) -> pd.DataFrame:
        rows = []
        for t in tokens:
            guidance = token_intake_guidance(t)
            rows.append({
                "Advies": guidance.action,
                "Waarom": guidance.why,
                "Status": _status_label(t["review_status"]),
                "Chain": t["chain"],
                "Token": t["asset"],
                "Contract": _contract_label(t.get("contract_address")),
                "Explorer": explorer_address_url(t["chain"], t.get("contract_address")),
                "Signaal": t.get("review_reason") or "",
                "Patroon": _unknown_hint(t),
                "Netto": _net_label(t),
                "Tx": int(t.get("tx_count") or 0),
                "In": int(t.get("in_count") or 0),
                "Uit": int(t.get("out_count") or 0),
                "Eerst": (t.get("first_seen") or "")[:10],
                "Laatst": (t.get("last_seen") or "")[:10],
                "Houders": t["holder_count"] if t.get("holder_count") is not None else "—",
                "Wallets": t["wallet_count"],
                "Bron": "handmatig" if t.get("decision_source") == "user" else "auto",
                "Importeren": bool(t["accepted"]),
            })
        return pd.DataFrame(rows)

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
                "Actie": row.get("method_name") or "",
                "Explorer": explorer_tx_url(token["chain"], row["tx_hash"]),
            })
        return pd.DataFrame(rows)

    def _context_button_key(prefix: str, token: dict) -> str:
        raw = f"{prefix}_{token['chain']}_{token['token_key']}"
        return "".join(ch if ch.isalnum() else "_" for ch in raw)

    groups = {
        INTAKE_REVIEW: [],
        INTAKE_NOISE: [],
        INTAKE_IMPORT: [],
        INTAKE_HIDDEN: [],
    }
    for token in all_tokens:
        groups[token_intake_guidance(token).bucket].append(token)
    for bucket, tokens in groups.items():
        groups[bucket] = sorted(tokens, key=token_intake_sort_key)

    status_counts = {
        "safe": sum(1 for t in all_tokens if t["review_status"] == "safe"),
        "unknown": sum(1 for t in all_tokens if t["review_status"] == "unknown"),
        "suspicious": sum(1 for t in all_tokens if t["review_status"] == "suspicious"),
        "scam": sum(1 for t in all_tokens if t["review_status"] == "scam"),
    }

    n_accepted = sum(1 for t in all_tokens if t["accepted"])
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Twijfel-lijst", len(groups[INTAKE_REVIEW]))
    m2.metric("Waarschijnlijk ruis", len(groups[INTAKE_NOISE]))
    m3.metric("Importeren", len(groups[INTAKE_IMPORT]))
    m4.metric("Verborgen", len(groups[INTAKE_HIDDEN]))
    st.caption(
        f"{n_accepted} van {len(all_tokens)} tokens geïmporteerd  ·  "
        f"{status_counts['safe']} zeker goed  ·  "
        f"{status_counts['unknown']} onbekend  ·  "
        f"{status_counts['suspicious']} verdacht  ·  "
        f"{status_counts['scam']} scam"
    )

    group_titles = {
        INTAKE_REVIEW: "Twijfel-lijst - handmatig controleren",
        INTAKE_NOISE: "Waarschijnlijk ruis - uitgevinkt laten",
        INTAKE_IMPORT: "Importeren - automatisch aangevinkt",
        INTAKE_HIDDEN: "Verborgen - scams en afgewezen tokens",
    }

    group_help = {
        INTAKE_REVIEW: "Dit is de enige lijst die echt aandacht nodig heeft.",
        INTAKE_NOISE: "Meestal passieve airdrops: laat uitgevinkt tenzij je het token herkent.",
        INTAKE_IMPORT: "Deze tokens zijn veilig genoeg bevonden en staan standaard aan.",
        INTAKE_HIDDEN: "Duidelijke scams en handmatig afgewezen tokens blijven auditbaar, maar staan uit portfolio.",
    }

    for bucket in (INTAKE_REVIEW, INTAKE_NOISE, INTAKE_IMPORT, INTAKE_HIDDEN):
        tokens = groups[bucket]
        if not tokens:
            continue
        expanded = bucket == INTAKE_REVIEW or (bucket == INTAKE_NOISE and not groups[INTAKE_REVIEW])
        with st.expander(f"{group_titles[bucket]} ({len(tokens)})", expanded=expanded):
            st.caption(group_help[bucket])
            if bucket in {INTAKE_REVIEW, INTAKE_NOISE}:
                st.caption("Loop door de transacties en kies per token direct importeren of afwijzen.")
                for t in tokens:
                    guidance = token_intake_guidance(t)
                    label_col, accept_col, reject_col = st.columns([4, 1, 1])
                    label_col.markdown(
                        f"**{t['asset']}** · `{_contract_label(t.get('contract_address'))}` · {guidance.action}"
                    )
                    if accept_col.button(
                        "Importeren",
                        key=_context_button_key("accept_from_tx", t),
                        use_container_width=True,
                        disabled=bool(t["accepted"]),
                    ):
                        save_token_selection_global([(t["chain"], t["token_key"], True)])
                        st.success(f"✅ {t['asset']} is geaccepteerd voor import.")
                        st.rerun()
                    if reject_col.button(
                        "Afwijzen",
                        key=_context_button_key("reject_from_tx", t),
                        use_container_width=True,
                    ):
                        save_token_selection_global([(t["chain"], t["token_key"], False)])
                        st.success(f"✅ {t['asset']} is afgewezen en verborgen.")
                        st.rerun()
                    tx_df = _tx_context_df(t)
                    if tx_df.empty:
                        st.caption("Geen transacties gevonden.")
                    else:
                        st.dataframe(
                            tx_df,
                            hide_index=True,
                            use_container_width=True,
                            column_config={
                                "Actie": st.column_config.TextColumn("Actie", disabled=True, width="medium"),
                                "Explorer": st.column_config.LinkColumn("Explorer", display_text="Open"),
                            },
                        )
            else:
                edited = st.data_editor(
                    _token_df(tokens),
                    column_config={
                        "Advies": st.column_config.TextColumn("Advies", disabled=True),
                        "Waarom": st.column_config.TextColumn("Waarom", disabled=True, width="large"),
                        "Status": st.column_config.TextColumn("Status", disabled=True),
                        "Chain": st.column_config.TextColumn("Chain", disabled=True),
                        "Token": st.column_config.TextColumn("Token", disabled=True),
                        "Contract": st.column_config.TextColumn("Contract", disabled=True),
                        "Explorer": st.column_config.LinkColumn("Explorer", display_text="Open"),
                        "Signaal": st.column_config.TextColumn("Signaal", disabled=True),
                        "Patroon": st.column_config.TextColumn("Patroon", disabled=True),
                        "Netto": st.column_config.TextColumn("Netto", disabled=True, width="small"),
                        "Tx": st.column_config.NumberColumn("Tx", disabled=True, width="small"),
                        "In": st.column_config.NumberColumn("In", disabled=True, width="small"),
                        "Uit": st.column_config.NumberColumn("Uit", disabled=True, width="small"),
                        "Eerst": st.column_config.TextColumn("Eerst", disabled=True, width="small"),
                        "Laatst": st.column_config.TextColumn("Laatst", disabled=True, width="small"),
                        "Houders": st.column_config.TextColumn("Houders", disabled=True, width="small"),
                        "Wallets": st.column_config.NumberColumn("Wallets", disabled=True, width="small"),
                        "Bron": st.column_config.TextColumn("Bron", disabled=True, width="small"),
                        "Importeren": st.column_config.CheckboxColumn("Importeren"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    key=f"{bucket}_editor",
                )

                if st.button("Selectie opslaan", key=f"save_{bucket}_btn"):
                    save_token_selection_global([
                        (t["chain"], t["token_key"], bool(edited.iloc[i]["Importeren"]))
                        for i, t in enumerate(tokens)
                    ])
                    st.success("✅ Opgeslagen.")
                    st.rerun()
