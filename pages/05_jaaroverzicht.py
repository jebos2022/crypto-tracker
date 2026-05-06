from decimal import Decimal

import pandas as pd
import streamlit as st

from core import coingecko
from core.models import CHAINS, format_token
from core.prices import available_years, snapshot_for_year, snapshot_price_ids
from core.rendement import compute_year, price_ids_for_year


st.title("Jaaroverzicht")
st.caption("Portfolio-snapshot op 1 januari en 31 december, met voorlopige werkelijk-rendement berekening.")


def _format_eur(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"€ {format_token(value, decimals=2)}"


def _format_price(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"€ {format_token(value, decimals=6)}"


def _valuation_label(row: dict) -> str:
    reasons = [
        reason
        for reason in (row.get("open_valuation_reason"), row.get("close_valuation_reason"))
        if reason
    ]
    if row.get("open_valuation_status") in {"manual_zero", "worthless"}:
        return reasons[0] if reasons else "Handmatig op nul gezet"
    if row.get("close_valuation_status") in {"manual_zero", "worthless"}:
        return reasons[0] if reasons else "Handmatig op nul gezet"
    return "-"


def _status_label(row: dict) -> str:
    return "deels onbekend" if row.get("incomplete") else "compleet"


years = available_years()
selected_year = st.selectbox("Jaar", years, index=len(years) - 1)
price_ids = sorted(set(snapshot_price_ids(selected_year)) | set(price_ids_for_year(selected_year)))
estimated_calls = len(price_ids)

used = coingecko.calls_today()
remaining = coingecko.budget_remaining()
st.caption(
    f"CoinGecko-budget vandaag: {used}/{coingecko.daily_call_budget()} gebruikt, "
    f"{remaining} resterend. Dit jaaroverzicht kost maximaal {estimated_calls} call(s)."
)

if "year_snapshot_loaded" not in st.session_state:
    st.session_state["year_snapshot_loaded"] = {}
if "year_rendement_loaded" not in st.session_state:
    st.session_state["year_rendement_loaded"] = {}

loaded_years = st.session_state["year_snapshot_loaded"]
loaded_rendement = st.session_state["year_rendement_loaded"]
if selected_year not in loaded_years:
    if not st.button("Laad jaaroverzicht", key="load_year_snapshot"):
        st.info("Klik om de snapshot en voorlopige rendementberekening voor dit jaar te laden.")
        st.stop()
    loaded_years[selected_year] = snapshot_for_year(selected_year)
    loaded_rendement[selected_year] = compute_year(selected_year)
elif selected_year not in loaded_rendement:
    loaded_rendement[selected_year] = compute_year(selected_year)

rows = loaded_years[selected_year]
rendement_rows = loaded_rendement[selected_year]
if not rows and not rendement_rows:
    st.info("Geen geaccepteerde transacties gevonden voor dit jaar.")
    st.stop()

if rows:
    table_rows = []
    total_open = Decimal("0")
    total_close = Decimal("0")
    partial = False
    for row in rows:
        if row["open_eur"] is not None:
            total_open += row["open_eur"]
        if row["close_eur"] is not None:
            total_close += row["close_eur"]
        partial = partial or row["incomplete"]
        table_rows.append({
            "Wallet": row["wallet"],
            "Chain": CHAINS.get(row["chain"], {}).get("label", row["chain"]),
            "Token": row["asset"],
            "Hoeveelheid 1-1": format_token(row["open_balance"]),
            "Prijs 1-1": _format_price(row["open_price"]),
            "EUR 1-1": _format_eur(row["open_eur"]),
            "Hoeveelheid 31-12": format_token(row["close_balance"]),
            "Prijs 31-12": _format_price(row["close_price"]),
            "EUR 31-12": _format_eur(row["close_eur"]),
            "Waardering": _valuation_label(row),
        })

    c1, c2, c3 = st.columns(3)
    c1.metric("Waarde 1-1", _format_eur(total_open))
    c2.metric("Waarde 31-12", _format_eur(total_close))
    c3.metric("Status", "Deels onbekend" if partial else "Compleet")

    st.dataframe(
        pd.DataFrame(table_rows),
        hide_index=True,
        width="stretch",
    )
else:
    st.info("Geen openstaand saldo op de peildatums voor dit jaar.")

st.divider()
st.subheader("Werkelijk rendement")
st.caption(
    "Voorlopige berekening: classificatie van swaps, staking, bridges en fiscale "
    "rapportage wordt in fase 6/8 verfijnd. Gas staat apart en telt niet mee in netto."
)

known_netto = [row["netto_eur"] for row in rendement_rows if row.get("netto_eur") is not None]
known_gas = [row["gas_eur"] for row in rendement_rows if row.get("gas_eur") is not None]
rendement_partial = any(row.get("incomplete") for row in rendement_rows)
total_netto = sum(known_netto, Decimal("0")) if known_netto else None
total_gas = sum(known_gas, Decimal("0")) if known_gas else None

r1, r2, r3 = st.columns(3)
r1.metric("Netto rendement", _format_eur(total_netto))
r2.metric("Gas", _format_eur(total_gas))
r3.metric("Status", "Deels onbekend" if rendement_partial else "Compleet")

rendement_table = [
    {
        "Wallet": row["wallet"],
        "Chain": CHAINS.get(row["chain"], {}).get("label", row["chain"]),
        "Token": row["asset"],
        "Open EUR": _format_eur(row["open_eur"]),
        "Close EUR": _format_eur(row["close_eur"]),
        "In EUR": _format_eur(row["in_eur"]),
        "Out EUR": _format_eur(row["out_eur"]),
        "Gas EUR": _format_eur(row["gas_eur"]),
        "Netto EUR": _format_eur(row["netto_eur"]),
        "Status": _status_label(row),
    }
    for row in rendement_rows
]

st.dataframe(
    pd.DataFrame(rendement_table),
    hide_index=True,
    width="stretch",
)
