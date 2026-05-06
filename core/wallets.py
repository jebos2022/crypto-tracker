from core.backup import create_backup
from core.db import get_connection


def get_wallets_for_fetch() -> list[dict]:
    """Return wallets in fetch order, including addresses."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, address FROM wallets ORDER BY id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_wallets_with_fetch_state() -> list[dict]:
    """Return wallets with the most recent fetch timestamp for display."""
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


def add_wallet(name: str, address: str) -> None:
    """Add a wallet. Raises sqlite3.IntegrityError for duplicate addresses."""
    clean_address = address.lower().strip()
    display_name = name.strip() or clean_address[:14] + "..."
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO wallets (name, address) VALUES (?, ?)",
            (display_name, clean_address),
        )
        conn.commit()
    finally:
        conn.close()


def delete_wallet(wallet_id: int) -> None:
    """Back up the DB and delete a wallet; dependent rows cascade."""
    create_backup()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM wallets WHERE id = ?", (wallet_id,))
        conn.commit()
    finally:
        conn.close()
