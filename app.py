from core.env import load_env

load_env()

import streamlit as st
from core.db import init_db
from core.backup import create_backup
from core.token_review import reclassify_all_token_reviews
from ui.styles import apply_design_system

init_db()
reclassify_all_token_reviews()

st.set_page_config(
    page_title="Crypto Tracker",
    page_icon="₿",
    layout="wide",
)

apply_design_system()

with st.sidebar:
    st.title("Crypto Tracker")
    st.caption("Lokale portfolio tracker")
    st.divider()
    st.page_link("pages/01_wallets.py",       label="EVM wallets",  icon="👛")
    st.page_link("pages/02_fetch.py",         label="Importeren",   icon="⬇️")
    st.page_link("pages/03_balances.py",      label="Balansen",     icon="📊")
    st.page_link("pages/04_transacties.py",   label="Transacties",  icon="🧾")
    st.divider()
    if st.button("Backup maken", use_container_width=True):
        path = create_backup()
        if path:
            st.success(f"Backup: {path.name}")
        else:
            st.info("Geen database om te backuppen.")

st.title("Crypto Tracker")
st.caption("Lokale portfolio tracker — wallets, import, balansen en transacties.")

NAV_ITEMS = [
    {
        "page": "pages/01_wallets.py",
        "icon": "👛",
        "title": "EVM wallets",
        "desc": "Walletadressen beheren voor Ethereum, Arbitrum, Base, Optimism, Polygon en BEAM.",
    },
    {
        "page": "pages/02_fetch.py",
        "icon": "⬇️",
        "title": "Importeren",
        "desc": "On-chain transacties ophalen en tokens reviewen.",
    },
    {
        "page": "pages/03_balances.py",
        "icon": "📊",
        "title": "Balansen",
        "desc": "Saldi per token en wallet, EUR-waardering en on-chain verificatie.",
    },
    {
        "page": "pages/04_transacties.py",
        "icon": "🧾",
        "title": "Transacties",
        "desc": "Ledger, swaps, gas fees en CSV-export voor fiscale aangiften.",
    },
]

cols = st.columns(4, gap="small")
for col, item in zip(cols, NAV_ITEMS):
    with col:
        st.markdown(
            f"""
            <div class="nav-card">
                <span class="nav-card-icon">{item['icon']}</span>
                <div class="nav-card-title">{item['title']}</div>
                <div class="nav-card-desc">{item['desc']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.page_link(item["page"], label=item["title"])
