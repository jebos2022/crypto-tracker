import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS wallets (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL,
    address  TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS wallet_chain_state (
    wallet_id    INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    chain        TEXT    NOT NULL,
    last_block   INTEGER NOT NULL DEFAULT 0,
    last_fetched TEXT,
    PRIMARY KEY (wallet_id, chain)
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


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        conn.executescript(INDICES_SQL)
        conn.commit()
    finally:
        conn.close()


def reset_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    init_db()
