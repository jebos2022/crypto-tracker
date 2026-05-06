import streamlit as st

from core.ledger import (
    csv_filename,
    logical_tx_groups,
)
from core.ledger_backfill import backfill_transaction_methods
from core.prices import eur_transactions
from core.transactions import (
    get_transaction_assets,
    get_transaction_chains,
    get_transaction_wallets,
    get_transaction_years,
    get_transactions,
)
from ui.transaction_tables import (
    chain_label,
    csv_df as build_csv_df,
    grouped_csv_df as build_grouped_csv_df,
    grouped_table_df as build_grouped_table_df,
    table_df as build_table_df,
    without_eur,
)


st.title("Transacties")
st.caption("Inspecteer geaccepteerde on-chain transacties per wallet, chain en token.")


wallets = get_transaction_wallets()

if not wallets:
    st.info("Nog geen EVM wallets. Voeg ze toe via **EVM wallets**.")
    st.stop()

wallet_options = ["Alle wallets"] + [w["name"] for w in wallets]

col_wallet, col_chain, col_year, col_asset, col_view, col_sort = st.columns([1.8, 1.8, 1.2, 1.8, 1.5, 1.3])

wallet_label = col_wallet.selectbox("Wallet", wallet_options, key="tx_wallet")
wallet_id = None if wallet_label == "Alle wallets" else next(
    w["id"] for w in wallets if w["name"] == wallet_label
)

chains = get_transaction_chains(wallet_id)
chain_label_to_key = {chain_label(chain): chain for chain in chains}
chain_options = ["Alle chains"] + list(chain_label_to_key.keys())
selected_chain_label = col_chain.selectbox("Chain", chain_options, key="tx_chain")
selected_chain = None if selected_chain_label == "Alle chains" else chain_label_to_key[selected_chain_label]

years = get_transaction_years(wallet_id, selected_chain)
year_options = ["Alle jaren"] + [str(year) for year in years]
selected_year_index = 1 if years else 0
selected_year_label = col_year.selectbox(
    "Jaar",
    year_options,
    index=selected_year_index,
    key="tx_year",
)
selected_year = None if selected_year_label == "Alle jaren" else int(selected_year_label)

assets = get_transaction_assets(wallet_id, selected_chain, selected_year)
asset_options = ["Alle tokens"] + assets
asset_label = col_asset.selectbox("Token", asset_options, key="tx_asset")
selected_asset = None if asset_label == "Alle tokens" else asset_label

sort_label = col_sort.selectbox(
    "Sortering",
    ["Nieuwste eerst", "Oudste eerst"],
    key="tx_sort",
)
descending = sort_label == "Nieuwste eerst"

view_label = col_view.selectbox(
    "Weergave",
    ["Transacties", "Boekingsregels"],
    key="tx_view",
)

raw_all_rows = get_transactions(wallet_id, selected_chain, selected_year, selected_asset, descending)
tx_eur_context = "|".join([
    str(wallet_id) if wallet_id is not None else "all-wallets",
    selected_chain or "all-chains",
    str(selected_year) if selected_year is not None else "all-years",
])
tx_eur_loaded_contexts = set(st.session_state.get("tx_eur_loaded_contexts", []))
if st.button("Laad EUR op tx-datum", key="tx_load_eur"):
    tx_eur_loaded_contexts.add(tx_eur_context)
    st.session_state["tx_eur_loaded_contexts"] = sorted(tx_eur_loaded_contexts)
load_eur = tx_eur_context in tx_eur_loaded_contexts
if load_eur:
    all_rows = eur_transactions(raw_all_rows)
else:
    st.caption("EUR-waarden worden pas geladen na klikken op **Laad EUR op tx-datum**.")
    all_rows = without_eur(raw_all_rows)
raw_rows = [row for row in all_rows if selected_asset is None or row["asset"] == selected_asset]
groups = logical_tx_groups(all_rows, selected_asset)

if view_label == "Boekingsregels":
    table_df = build_table_df(raw_rows)
    csv_df = build_csv_df(raw_rows)
    visible_count = len(raw_rows)
else:
    table_df = build_grouped_table_df(groups)
    csv_df = build_grouped_csv_df(groups)
    visible_count = len(groups)

c1, c2, c3 = st.columns(3)
c1.metric(view_label, visible_count)
if view_label == "Transacties":
    c2.metric("Boekingsregels", sum(group["row_count"] for group in groups))
else:
    c2.metric("Transacties", len(groups))
visible_assets = (
    {asset for group in groups for asset in group["assets"]}
    if view_label == "Transacties"
    else {r["asset"] for r in raw_rows}
)
c3.metric("Tokens", len(visible_assets))

download_name = csv_filename(
    wallet_label,
    selected_chain_label,
    asset_label,
    year_label=selected_year_label,
)
col_download, col_backfill = st.columns([1, 1])
col_download.download_button(
    "Download CSV",
    data=csv_df.to_csv(index=False).encode("utf-8"),
    file_name=download_name,
    mime="text/csv",
    key="tx_csv_download",
    disabled=False,
)

if col_backfill.button(
    "Acties aanvullen",
    key="tx_method_backfill",
    help="Haalt method/action metadata op voor bestaande txlist-rijen. Verandert geen transacties of balansen.",
):
    progress = st.progress(0, text="Acties ophalen...")
    summary = backfill_transaction_methods(
        wallet_id=wallet_id,
        chain=selected_chain,
        progress_fn=lambda f, t: progress.progress(min(f, 0.99), text=t),
    )
    progress.progress(1.0, text="Klaar")
    if summary.errors:
        for error in summary.errors:
            st.warning(error)
    st.success(f"Acties aangevuld: {summary.updated} rij(en) bijgewerkt uit {summary.scanned} txlist-records.")
    st.rerun()

if visible_count:
    st.dataframe(
        table_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Datum": st.column_config.TextColumn("Datum"),
            "Wallet": st.column_config.TextColumn("Wallet"),
            "Chain": st.column_config.TextColumn("Chain"),
            "Type": st.column_config.TextColumn("Type"),
            "Actie": st.column_config.TextColumn("Actie"),
            "Signaal": st.column_config.TextColumn("Signaal"),
            "Bedrag": st.column_config.TextColumn("Bedrag"),
            "Uit": st.column_config.TextColumn("Uit"),
            "In": st.column_config.TextColumn("In"),
            "Gas": st.column_config.TextColumn("Gas"),
            "Asset": st.column_config.TextColumn("Asset"),
            "EUR (op tx-datum)": st.column_config.TextColumn("EUR (op tx-datum)"),
            "Tx": st.column_config.TextColumn("Tx"),
            "Bron": st.column_config.TextColumn("Bron"),
            "Explorer": st.column_config.LinkColumn("Explorer", display_text="Open"),
        },
    )
else:
    st.info("Geen transacties gevonden voor deze filters.")
    st.dataframe(
        table_df,
        width="stretch",
        hide_index=True,
        column_config={
            "Explorer": st.column_config.LinkColumn("Explorer", display_text="Open"),
        },
    )
