import sqlite3
from pathlib import Path

# Store the DB outside iCloud Drive — iCloud can revert SQLite files on sync.
# ~/Library/Application Support is the macOS convention for local app data.
DB_PATH = Path.home() / "Library" / "Application Support" / "crypto-tracker" / "portfolio.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wallets (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL,
    address  TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS wallet_chain_state (
    wallet_id    INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    chain        TEXT    NOT NULL,
    endpoint     TEXT    NOT NULL DEFAULT 'all',
    last_block   INTEGER NOT NULL DEFAULT 0,
    last_fetched TEXT,
    PRIMARY KEY (wallet_id, chain, endpoint)
);

CREATE TABLE IF NOT EXISTS transactions (
    id               TEXT    PRIMARY KEY,
    wallet_id        INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    chain            TEXT    NOT NULL,
    timestamp        TEXT    NOT NULL,
    block_number     INTEGER NOT NULL DEFAULT 0,
    tx_hash          TEXT    NOT NULL,
    type             TEXT    NOT NULL,
    asset            TEXT    NOT NULL,
    contract_address TEXT,
    amount           TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    UNIQUE (tx_hash, wallet_id)
);

CREATE TABLE IF NOT EXISTS token_review (
    wallet_id        INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    chain            TEXT    NOT NULL,
    asset            TEXT    NOT NULL,
    contract_address TEXT,
    accepted         INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (wallet_id, chain, asset)
);

-- token_meta: per-contract decimals + symbol, harvested from tokentx rows.
-- Needed to scale raw balances from `tokenbalance` for verification.
CREATE TABLE IF NOT EXISTS token_meta (
    chain            TEXT    NOT NULL,
    contract_address TEXT    NOT NULL,
    symbol           TEXT,
    decimals         INTEGER NOT NULL DEFAULT 18,
    last_seen        TEXT,
    PRIMARY KEY (chain, contract_address)
);

-- token_metadata: Etherscan tokeninfo enrichment (verification, holders, social presence).
CREATE TABLE IF NOT EXISTS token_metadata (
    contract_address TEXT    NOT NULL,
    chain            TEXT    NOT NULL,
    verified         INTEGER NOT NULL DEFAULT 0,
    holder_count     INTEGER,
    has_website      INTEGER NOT NULL DEFAULT 0,
    has_social       INTEGER NOT NULL DEFAULT 0,
    fetched_at       TEXT    NOT NULL,
    PRIMARY KEY (contract_address, chain)
);
"""

INDICES_SQL = """
CREATE INDEX IF NOT EXISTS idx_tx_wallet    ON transactions(wallet_id);
CREATE INDEX IF NOT EXISTS idx_tx_chain     ON transactions(chain);
CREATE INDEX IF NOT EXISTS idx_tx_asset     ON transactions(asset);
CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_tx_hash      ON transactions(tx_hash);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


# Endpoints we track per (wallet, chain) — must stay in sync with core.fetcher.
TRACKED_ENDPOINTS: tuple[str, ...] = ("tokentx", "txlist", "txlistinternal")


def _migrate_wallet_chain_state(conn: sqlite3.Connection) -> None:
    """
    Add the `endpoint` column + composite PK to `wallet_chain_state` if the
    DB was created with the old schema. Idempotent — safe to run on every
    init_db().

    Behaviour:
      * Old rows (no endpoint) are duplicated for each endpoint we track,
        seeding all three with the previous combined `last_block`. This
        avoids re-fetching everything from block 0 on first run after upgrade.
      * If the column already exists, this is a no-op.
    """
    cols = [r[1] for r in conn.execute("PRAGMA table_info(wallet_chain_state)").fetchall()]
    if not cols or "endpoint" in cols:
        return  # fresh DB or already migrated

    conn.execute("ALTER TABLE wallet_chain_state RENAME TO _wallet_chain_state_old")
    conn.executescript("""
        CREATE TABLE wallet_chain_state (
            wallet_id    INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
            chain        TEXT    NOT NULL,
            endpoint     TEXT    NOT NULL DEFAULT 'all',
            last_block   INTEGER NOT NULL DEFAULT 0,
            last_fetched TEXT,
            PRIMARY KEY (wallet_id, chain, endpoint)
        );
    """)
    for endpoint in TRACKED_ENDPOINTS:
        conn.execute(
            """
            INSERT INTO wallet_chain_state (wallet_id, chain, endpoint, last_block, last_fetched)
            SELECT wallet_id, chain, ?, last_block, last_fetched
            FROM _wallet_chain_state_old
            """,
            (endpoint,),
        )
    conn.execute("DROP TABLE _wallet_chain_state_old")


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        _migrate_wallet_chain_state(conn)
        conn.executescript(INDICES_SQL)
        conn.commit()
    finally:
        conn.close()


def reset_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()


def clear_transactions() -> None:
    """Wipe transactions, fetch state, and token review — but keep wallets."""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM transactions")
        conn.execute("DELETE FROM wallet_chain_state")
        conn.execute("DELETE FROM token_review")
        # token_meta is intentionally kept — decimals don't change and re-fetch
        # would just re-populate identical rows. Wipe via reset_db() if needed.
        conn.commit()
    finally:
        conn.close()
