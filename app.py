from core.env import load_env

load_env()

import streamlit as st
from core.db import init_db
from core.backup import create_backup
from core.token_review import reclassify_all_token_reviews

init_db()
reclassify_all_token_reviews()

st.set_page_config(
    page_title="Crypto Tracker",
    page_icon="₿",
    layout="wide",
)

with st.sidebar:
    st.title("Crypto Tracker")
    st.caption("Lokale portfolio tracker")
    st.divider()
    st.page_link("pages/01_wallets.py",  label="EVM wallets", icon="👛")
    st.page_link("pages/02_fetch.py",    label="Importeren", icon="⬇️")
    st.page_link("pages/03_balances.py", label="Balansen",  icon="📊")
    st.page_link("pages/04_transacties.py", label="Transacties", icon="🧾")
    st.divider()
    if st.button("Backup maken", use_container_width=True):
        path = create_backup()
        if path:
            st.success(f"Backup: {path.name}")
        else:
            st.info("Geen database om te backuppen.")

st.title("Crypto Tracker")
st.caption("Portfolio-overzicht, import, balansen en transacties.")

col_wallets, col_fetch, col_balances, col_transactions = st.columns(4)

with col_wallets:
    st.page_link("pages/01_wallets.py", label="EVM wallets", icon="👛")
    st.caption("Walletadressen beheren.")

with col_fetch:
    st.page_link("pages/02_fetch.py", label="Importeren", icon="⬇️")
    st.caption("On-chain data ophalen en tokens reviewen.")

with col_balances:
    st.page_link("pages/03_balances.py", label="Balansen", icon="📊")
    st.caption("Geaccepteerde tokens en saldi.")

with col_transactions:
    st.page_link("pages/04_transacties.py", label="Transacties", icon="🧾")
    st.caption("Ledger, swaps, gas en CSV-export.")
