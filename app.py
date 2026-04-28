from dotenv import load_dotenv
load_dotenv()

import streamlit as st
from core.db import init_db
from core.backup import create_backup

init_db()

st.set_page_config(
    page_title="Crypto Tracker",
    page_icon="₿",
    layout="wide",
)

with st.sidebar:
    st.title("Crypto Tracker")
    st.caption("Fase 1 — MVP")
    st.divider()
    st.page_link("pages/01_wallets.py",  label="Wallets",   icon="👛")
    st.page_link("pages/02_fetch.py",    label="Importeren", icon="⬇️")
    st.page_link("pages/03_balances.py", label="Balansen",  icon="📊")
    st.divider()
    if st.button("Backup maken", use_container_width=True):
        path = create_backup()
        if path:
            st.success(f"Backup: {path.name}")
        else:
            st.info("Geen database om te backuppen.")

st.title("Crypto Tracker")
st.caption("Gebruik de navigatie in de sidebar.")
