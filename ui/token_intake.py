import pandas as pd
import streamlit as st

from core.token_review import (
    INTAKE_HIDDEN,
    INTAKE_IMPORT,
    INTAKE_NOISE,
    INTAKE_REVIEW,
    accept_recommended_tokens,
    auto_reject_scams,
    count_enrichable_contracts,
    count_public_enrichable_contracts,
    enrich_public_sources,
    enrich_tokens,
    reject_all_tokens,
    save_token_selection_global,
    token_intake_guidance,
    token_intake_sort_key,
)
from core.token_valuation import (
    VALUATION_ACTIVE,
    VALUATION_MANUAL_ZERO,
    VALUATION_UNKNOWN,
    VALUATION_WORTHLESS,
    save_global_valuations,
)
from ui.token_intake_tables import (
    context_button_key,
    contract_label,
    token_df,
    tx_context_df,
    valuation_label,
)


def render_token_intake(all_tokens: list[dict]) -> None:
    valuation_label_to_status = {
        "Marktprijs": VALUATION_ACTIVE,
        "Onbekend": VALUATION_UNKNOWN,
        "Handmatig 0": VALUATION_MANUAL_ZERO,
        "Waardeloos": VALUATION_WORTHLESS,
    }
    valuation_status_to_label = {status: label for label, status in valuation_label_to_status.items()}

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
        _run_full_intake()

    if public_col.button(
        f"Publieke check ({n_public_contracts} tokens)",
        key="public_enrich_btn",
        use_container_width=True,
        help="Checkt CoinGecko token lists, CoinGecko contract lookup en GoPlus security. Resultaten worden gecachet.",
    ):
        _run_public_enrichment()
    if enrich_col.button(
        f"Metadata ophalen ({n_contracts} tokens)",
        key="enrich_btn",
        use_container_width=True,
        help="Haalt verificatie, houders en social info op via Etherscan. Duurt ~30 sec.",
    ):
        _run_metadata_enrichment()
    if n_enriched:
        enrich_status.caption(f"{n_enriched} van {n_contracts} tokens hebben metadata.")

    _render_bulk_actions()
    groups = _group_tokens(all_tokens)
    _render_intake_metrics(all_tokens, groups)
    _render_token_groups(groups, valuation_status_to_label)
    _render_manual_valuation(all_tokens, valuation_label_to_status, valuation_status_to_label)


def _run_full_intake() -> None:
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


def _run_public_enrichment() -> None:
    prog = st.progress(0, text="Publieke bronnen ophalen...")
    updated, failed = enrich_public_sources(
        progress_fn=lambda f, t: prog.progress(min(f, 0.99), text=t)
    )
    prog.progress(1.0, text="Klaar")
    st.success(f"✅ {updated} publieke signalen bijgewerkt, {failed} fout(en).")
    st.rerun()


def _run_metadata_enrichment() -> None:
    prog = st.progress(0, text="Metadata ophalen...")
    enriched, failed = enrich_tokens(
        progress_fn=lambda f, t: prog.progress(min(f, 0.99), text=t)
    )
    prog.progress(1.0, text="Klaar")
    st.success(f"✅ {enriched} tokens verrijkt, {failed} niet beschikbaar.")
    st.rerun()


def _render_bulk_actions() -> None:
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


def _group_tokens(all_tokens: list[dict]) -> dict[str, list[dict]]:
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
    return groups


def _render_intake_metrics(all_tokens: list[dict], groups: dict[str, list[dict]]) -> None:
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


def _render_token_groups(groups: dict[str, list[dict]], valuation_status_to_label: dict[str, str]) -> None:
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
                _render_review_tokens(tokens)
            else:
                _render_table_tokens(bucket, tokens, valuation_status_to_label)


def _render_review_tokens(tokens: list[dict]) -> None:
    st.caption("Loop door de transacties en kies per token direct importeren of afwijzen.")
    for token in tokens:
        guidance = token_intake_guidance(token)
        label_col, accept_col, reject_col = st.columns([4, 1, 1])
        label_col.markdown(
            f"**{token['asset']}** · `{contract_label(token.get('contract_address'))}` · {guidance.action}"
        )
        if accept_col.button(
            "Importeren",
            key=context_button_key("accept_from_tx", token),
            use_container_width=True,
            disabled=bool(token["accepted"]),
        ):
            save_token_selection_global([(token["chain"], token["token_key"], True)])
            st.success(f"✅ {token['asset']} is geaccepteerd voor import.")
            st.rerun()
        if reject_col.button(
            "Afwijzen",
            key=context_button_key("reject_from_tx", token),
            use_container_width=True,
        ):
            save_token_selection_global([(token["chain"], token["token_key"], False)])
            st.success(f"✅ {token['asset']} is afgewezen en verborgen.")
            st.rerun()
        tx_df = tx_context_df(token)
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


def _render_table_tokens(bucket: str, tokens: list[dict], valuation_status_to_label: dict[str, str]) -> None:
    edited = st.data_editor(
        token_df(tokens, valuation_status_to_label),
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
            "Waardering": st.column_config.TextColumn("Waardering", disabled=True, width="small"),
            "Vanaf": st.column_config.TextColumn("Vanaf", disabled=True, width="small"),
            "Notitie": st.column_config.TextColumn("Notitie", disabled=True),
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


def _render_manual_valuation(
    all_tokens: list[dict],
    valuation_label_to_status: dict[str, str],
    valuation_status_to_label: dict[str, str],
) -> None:
    with st.expander("Handmatige waardering", expanded=False):
        st.caption("Gebruik dit alleen als je bewust een token vanaf een datum op nul wilt waarderen.")
        valuation_df = pd.DataFrame([
            {
                "Chain": token["chain"],
                "Token": token["asset"],
                "Contract": contract_label(token.get("contract_address")),
                "Waardering": valuation_label(token.get("valuation_status"), valuation_status_to_label),
                "Vanaf": token.get("valuation_effective_date") or "",
                "Notitie": token.get("valuation_reason") or "",
            }
            for token in all_tokens
        ])
        edited_valuations = st.data_editor(
            valuation_df,
            column_config={
                "Chain": st.column_config.TextColumn("Chain", disabled=True),
                "Token": st.column_config.TextColumn("Token", disabled=True),
                "Contract": st.column_config.TextColumn("Contract", disabled=True),
                "Waardering": st.column_config.SelectboxColumn(
                    "Waardering",
                    options=list(valuation_label_to_status),
                ),
                "Vanaf": st.column_config.TextColumn("Vanaf"),
                "Notitie": st.column_config.TextColumn("Notitie"),
            },
            hide_index=True,
            use_container_width=True,
            key="manual_valuation_editor",
        )
        if st.button("Waarderingen opslaan", key="save_manual_valuations"):
            try:
                save_global_valuations([
                    (
                        token["chain"],
                        token["token_key"],
                        valuation_label_to_status[str(edited_valuations.iloc[i]["Waardering"])],
                        str(edited_valuations.iloc[i]["Vanaf"] or ""),
                        str(edited_valuations.iloc[i]["Notitie"] or ""),
                    )
                    for i, token in enumerate(all_tokens)
                ])
            except ValueError as exc:
                st.error(f"Niet opgeslagen: {exc}")
            else:
                st.success("✅ Waarderingen opgeslagen.")
                st.rerun()
