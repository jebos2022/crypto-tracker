from decimal import Decimal

import streamlit as st
import pandas as pd

from core.balances import get_balances, get_bridge_summary, get_wallets, summarize_balances
from core.models import CHAINS, format_eur, format_token
from core.balance_check import verify_balances
from core.prices import eur_balances_today
from ui.styles import apply_design_system

apply_design_system()

st.title("Balansen")
st.caption("Som van alle transacties per token per wallet. Alleen tokens waarvoor 'Importeren' aangevinkt is.")

ZERO_THRESHOLD = Decimal("0.000001")


def _format_eur_row(row: dict) -> str:
    value = format_eur(row.get("eur_value"))
    return f"{value} (handmatig 0)" if row.get("valuation_manual") else value


def _valuation_label(row: dict) -> str:
    if row.get("valuation_manual"):
        return row.get("valuation_reason") or "Handmatig op nul gezet"
    return "-"


def _without_eur(rows: list[dict]) -> list[dict]:
    return [
        {
            **row,
            "coingecko_id": None,
            "eur_price": None,
            "eur_value": None,
            "eur_missing": False,
            "valuation_manual": False,
            "valuation_reason": "",
        }
        for row in rows
    ]


def _chain_list(chains: set[str]) -> str:
    return ", ".join(CHAINS.get(chain, {}).get("label", chain) for chain in sorted(chains))


def _asset_detail_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Wallet": row["wallet"],
        "Chain": CHAINS.get(row["chain"], {}).get("label", row["chain"]),
        "Token": row.get("display_asset") or row["asset"],
        "Contract": row.get("contract_address") or "native",
        "Balans": format_token(row["balance"]),
        "Waarde (EUR)": _format_eur_row(row),
    } for row in rows])


def _asset_summary_title(item: dict) -> str:
    eur = format_eur(item["eur_value"] if item["eur_known"] else None)
    suffix = " · deels onbekend" if item["eur_missing"] else ""
    return f"{item['asset']} details · {format_token(item['balance'])} · {eur}{suffix}"


def _asset_overview_df(items: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{
        "Asset": item["asset"],
        "Balans": format_token(item["balance"]),
        "Waarde (EUR)": format_eur(item["eur_value"] if item["eur_known"] else None),
        "Chains": _chain_list(item["chains"]),
        "Wallets": ", ".join(sorted(item["wallets"])),
        "Tokens": ", ".join(sorted(item["tokens"])),
        "Status": "deels onbekend" if item["eur_missing"] else "",
    } for item in items])


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

wallets = get_wallets()

if not wallets:
    st.info("Nog geen wallets. Voeg ze toe via **Wallets**.")
    st.stop()

col_sel, col_toggle, col_refresh = st.columns([3, 1, 1])
options = ["Alle wallets"] + [w["name"] for w in wallets]
selected_label = col_sel.selectbox("Wallet", options, key="bal_wallet_sel")
selected_id = None if selected_label == "Alle wallets" else next(
    w["id"] for w in wallets if w["name"] == selected_label
)
hide_zero = col_toggle.checkbox("Verberg nullen", value=True, key="hide_zero")
if col_refresh.button(
    "Ververs",
    key="refresh_balances",
    width="stretch",
    help="Lees saldi opnieuw uit de database en wis oude on-chain verificatie.",
):
    st.session_state.pop("balance_check", None)
    st.rerun()

raw_balances = get_balances(selected_id)
balance_eur_context = str(selected_id) if selected_id is not None else "all"
balance_eur_loaded_contexts = set(st.session_state.get("balance_eur_loaded_contexts", []))
if st.button("Laad EUR-prijzen", key="load_balance_eur"):
    balance_eur_loaded_contexts.add(balance_eur_context)
    st.session_state["balance_eur_loaded_contexts"] = sorted(balance_eur_loaded_contexts)
load_eur = balance_eur_context in balance_eur_loaded_contexts
if load_eur:
    balances = eur_balances_today(raw_balances)
else:
    st.caption("EUR-prijzen worden pas geladen na klikken op **Laad EUR-prijzen**.")
    balances = _without_eur(raw_balances)
bridge_summary = get_bridge_summary(selected_id)

if not balances:
    st.info("Geen balansen gevonden. Haal transacties op via **Importeren** en vink tokens aan.")
    st.stop()

display_balances = []
for b in balances:
    bal = b["balance"]
    if abs(bal) < ZERO_THRESHOLD:
        bal = Decimal("0")
    if hide_zero and bal == 0:
        continue
    display_balances.append({**b, "balance": bal})

asset_summaries, position_rows = summarize_balances(display_balances)

# Build display rows
rows = []
negatives = 0
bridge_explained = 0

for b in display_balances:
    bal = b["balance"]
    is_neg = bal < 0

    bridged_out    = Decimal("0")
    is_bridge_caused = False
    if is_neg:
        negatives += 1
        key = (b["wallet"], b["chain"], b["asset"], b.get("contract_address"))
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
        "Token":  b.get("display_asset") or b["asset"],
        "Balans": format_token(bal),
        "Waarde (EUR)": _format_eur_row(b),
        "Waardering": _valuation_label(b),
        "_zero":  bal == 0,
        "_neg":   is_neg,
        "_bridge": is_bridge_caused,
        "_eur_value": b["eur_value"],
        "_eur_missing": b["eur_missing"],
    })

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
total_eur    = sum((r["_eur_value"] for r in rows if r["_eur_value"] is not None), Decimal("0"))
eur_partial  = load_eur and any(r["_eur_missing"] for r in rows)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Tokens", total_tokens)
c2.metric("Positief saldo", positive)
c3.metric("⚠️ Negatief", negatives)
eur_delta_parts = []
if eur_partial:
    eur_delta_parts.append("deels onbekend")
if load_eur:
    eur_delta_parts.append("excl. live staking")
c4.metric(
    "Waarde EUR",
    format_eur(total_eur) if load_eur else "Niet geladen",
    delta=" · ".join(eur_delta_parts) if eur_delta_parts else None,
)

st.divider()
st.subheader("Overzicht per asset")

if asset_summaries:
    st.dataframe(_asset_overview_df(asset_summaries), width="stretch", hide_index=True)
    for item in asset_summaries:
        with st.expander(_asset_summary_title(item), expanded=False):
            st.dataframe(_asset_detail_df(item["details"]), width="stretch", hide_index=True)
else:
    st.info("Geen gewone asset-balansen zichtbaar met deze filters.")

if position_rows:
    st.subheader("Posities")
    st.caption("Staking wrappers worden niet als gewone tokens geprijsd; de waarde volgt later uit stake/unstake-reconstructie.")
    st.dataframe(_asset_detail_df(position_rows), width="stretch", hide_index=True)

st.divider()
st.subheader("Details per wallet en chain")

display_df = pd.DataFrame([{k: v for k, v in r.items() if not k.startswith("_")} for r in rows])

st.dataframe(
    display_df,
    width="stretch",
    hide_index=True,
    column_config={
        "":       st.column_config.TextColumn("", width="small"),
        "Wallet": st.column_config.TextColumn("Wallet"),
        "Chain":  st.column_config.TextColumn("Chain"),
        "Token":  st.column_config.TextColumn("Token"),
        "Balans": st.column_config.TextColumn("Balans"),
        "Waarde (EUR)": st.column_config.TextColumn("Waarde (EUR)"),
        "Waardering": st.column_config.TextColumn("Waardering"),
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
        width="stretch",
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
        for (w, ch, asset, _contract), agg in sorted(bridge_summary.items()):
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
            width="stretch",
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
    from core.staking import fetch_beam_staking_balance

    beam_wallets = get_wallets()

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
        st.dataframe(pd.DataFrame(staking_rows), hide_index=True, width="stretch")
        st.caption("Dit live staking saldo telt niet mee in de Waarde EUR-metric hierboven.")
    else:
        st.info("Geen BEAM staking gevonden voor de bekende wallets.")
