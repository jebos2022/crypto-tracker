import streamlit as st
from core.db import get_connection
from core.backup import create_backup

st.title("EVM wallets")
st.caption(
    "Beheer je EVM-walletadressen. Deze adressen worden opgehaald op Ethereum, "
    "Arbitrum, Base, Optimism, Polygon en BEAM."
)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_wallets() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT w.id, w.name, w.address, "
            "  (SELECT MAX(wcs.last_fetched) FROM wallet_chain_state wcs WHERE wcs.wallet_id = w.id) AS last_fetched "
            "FROM wallets w ORDER BY w.id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _add_wallet(name: str, address: str) -> str | None:
    """Insert wallet. Returns error message or None on success."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO wallets (name, address) VALUES (?, ?)",
            (name.strip() or address[:14] + "...", address.lower().strip()),
        )
        conn.commit()
        return None
    except Exception as e:
        return str(e)
    finally:
        conn.close()


def _delete_wallet(wallet_id: int) -> None:
    create_backup()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

wallets = _get_wallets()

if wallets:
    st.subheader(f"{len(wallets)} EVM wallet(s)")
    for w in wallets:
        with st.container(border=True):
            c1, c2, c3 = st.columns([2, 6, 1])
            c1.markdown(f"**{w['name']}**")
            c2.caption(w["address"])
            c3.caption(w["last_fetched"][:10] if w["last_fetched"] else "Nooit")

            if st.session_state.get(f"confirm_del_{w['id']}"):
                st.warning(f"Verwijder **{w['name']}**? Alle transacties voor deze wallet worden ook verwijderd.")
                col_yes, col_no = st.columns(2)
                if col_yes.button("Ja, verwijderen", key=f"del_yes_{w['id']}", type="primary"):
                    _delete_wallet(w["id"])
                    st.session_state.pop(f"confirm_del_{w['id']}", None)
                    st.rerun()
                if col_no.button("Annuleren", key=f"del_no_{w['id']}"):
                    st.session_state.pop(f"confirm_del_{w['id']}", None)
                    st.rerun()
            else:
                if c3.button("✕", key=f"del_{w['id']}"):
                    st.session_state[f"confirm_del_{w['id']}"] = True
                    st.rerun()
else:
    st.info("Nog geen EVM wallets. Voeg hieronder je eerste wallet toe.")

st.divider()
st.subheader("EVM wallet toevoegen")

with st.form("add_wallet_form", clear_on_submit=True):
    col_name, col_addr = st.columns([2, 5])
    new_name = col_name.text_input("Naam (optioneel)", placeholder="Mijn wallet")
    new_addr = col_addr.text_input("Adres (0x…)", placeholder="0xabc123…")
    submitted = st.form_submit_button("Toevoegen", type="primary")

if submitted:
    addr_clean = new_addr.strip().lower()
    if not addr_clean.startswith("0x") or len(addr_clean) != 42:
        st.error("Ongeldig adres — moet beginnen met 0x en 42 tekens lang zijn.")
    else:
        err = _add_wallet(new_name, addr_clean)
        if err:
            if "UNIQUE" in err:
                st.error("Dit adres staat al in de lijst.")
            else:
                st.error(f"Fout: {err}")
        else:
            st.success("✅ Wallet toegevoegd.")
            st.rerun()
