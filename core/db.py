import sqlite3
from pathlib import Path

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
    from_address     TEXT,
    to_address       TEXT,
    type             TEXT    NOT NULL,
    asset            TEXT    NOT NULL,
    contract_address TEXT,
    amount           TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    method_id        TEXT,
    method_name      TEXT,
    UNIQUE (tx_hash, wallet_id, source)
);

CREATE TABLE IF NOT EXISTS token_review (
    wallet_id        INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
    chain            TEXT    NOT NULL,
    token_key        TEXT    NOT NULL,
    asset            TEXT    NOT NULL,
    contract_address TEXT,
    accepted         INTEGER NOT NULL DEFAULT 0,
    review_status    TEXT    NOT NULL DEFAULT 'unknown',
    review_reason    TEXT    NOT NULL DEFAULT 'Nog onvoldoende metadata',
    decision_source  TEXT    NOT NULL DEFAULT 'auto',
    decision_updated_at TEXT,
    valuation_status TEXT    NOT NULL DEFAULT 'active',
    valuation_effective_date TEXT,
    valuation_reason TEXT,
    PRIMARY KEY (wallet_id, chain, token_key)
);

CREATE TABLE IF NOT EXISTS token_meta (
    chain            TEXT    NOT NULL,
    contract_address TEXT    NOT NULL,
    symbol           TEXT,
    decimals         INTEGER NOT NULL DEFAULT 18,
    last_seen        TEXT,
    PRIMARY KEY (chain, contract_address)
);

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

CREATE TABLE IF NOT EXISTS token_public_evidence (
    chain            TEXT    NOT NULL,
    contract_address TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    status           TEXT    NOT NULL,
    name             TEXT,
    symbol           TEXT,
    reason           TEXT,
    payload_json     TEXT,
    fetched_at       TEXT    NOT NULL,
    PRIMARY KEY (chain, contract_address, source)
);

CREATE TABLE IF NOT EXISTS token_source_cache (
    source     TEXT NOT NULL,
    chain      TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, chain)
);

CREATE TABLE IF NOT EXISTS price_cache (
    coingecko_id TEXT NOT NULL,
    date         TEXT NOT NULL,
    eur          TEXT NOT NULL,
    source       TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    PRIMARY KEY (coingecko_id, date)
);

CREATE TABLE IF NOT EXISTS price_fetch_log (
    date   TEXT    NOT NULL,
    source TEXT    NOT NULL,
    count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, source)
);
"""

INDICES_SQL = """
CREATE INDEX IF NOT EXISTS idx_tx_wallet    ON transactions(wallet_id);
CREATE INDEX IF NOT EXISTS idx_tx_chain     ON transactions(chain);
CREATE INDEX IF NOT EXISTS idx_tx_asset     ON transactions(asset);
CREATE INDEX IF NOT EXISTS idx_tx_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_tx_hash      ON transactions(tx_hash);
CREATE INDEX IF NOT EXISTS idx_token_review_asset ON token_review(chain, asset);
CREATE INDEX IF NOT EXISTS idx_token_review_contract ON token_review(chain, contract_address);
CREATE INDEX IF NOT EXISTS idx_token_public_evidence_contract ON token_public_evidence(chain, contract_address);
CREATE INDEX IF NOT EXISTS idx_price_cache_date ON price_cache(date);
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


def _migrate_tx_dedup_constraint(conn: sqlite3.Connection) -> None:
    """
    Change UNIQUE (tx_hash, wallet_id) → UNIQUE (tx_hash, wallet_id, source).
    Idempotent — safe to run on every init_db().

    Root cause: a transaction that moves both ETH and tokens (e.g. "buy tokens
    with ETH") produces a tokentx row AND a txlist row with the same outer
    tx_hash. The old 2-column constraint blocks the txlist TRANSFER_OUT because
    the tx_hash is already occupied by the tokentx row. Fix: allow the same
    tx_hash per wallet as long as the source differs.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='transactions'"
    ).fetchone()
    if not row:
        return  # table not yet created — SCHEMA_SQL will create it correctly
    table_sql = row[0] or ""
    if "wallet_id, source" in table_sql:
        return  # already migrated

    conn.execute("ALTER TABLE transactions RENAME TO _transactions_old")
    conn.executescript("""
        CREATE TABLE transactions (
            id               TEXT    PRIMARY KEY,
            wallet_id        INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
            chain            TEXT    NOT NULL,
            timestamp        TEXT    NOT NULL,
            block_number     INTEGER NOT NULL DEFAULT 0,
            tx_hash          TEXT    NOT NULL,
            from_address     TEXT,
            to_address       TEXT,
            type             TEXT    NOT NULL,
            asset            TEXT    NOT NULL,
            contract_address TEXT,
            amount           TEXT    NOT NULL,
            source           TEXT    NOT NULL,
            method_id        TEXT,
            method_name      TEXT,
            UNIQUE (tx_hash, wallet_id, source)
        );
        INSERT INTO transactions
          (id, wallet_id, chain, timestamp, block_number, tx_hash,
           from_address, to_address, type, asset, contract_address,
           amount, source, method_id, method_name)
        SELECT
           id, wallet_id, chain, timestamp, block_number, tx_hash,
           NULL, NULL, type, asset, contract_address, amount, source, NULL, NULL
        FROM _transactions_old;
        DROP TABLE _transactions_old;
    """)


def _migrate_tx_method_columns(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if not cols:
        return
    if "method_id" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN method_id TEXT")
    if "method_name" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN method_name TEXT")


def _migrate_tx_address_columns(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(transactions)").fetchall()]
    if not cols:
        return
    if "from_address" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN from_address TEXT")
    if "to_address" not in cols:
        conn.execute("ALTER TABLE transactions ADD COLUMN to_address TEXT")


def _token_key_sql(table_alias: str = "t") -> str:
    return (
        f"CASE WHEN {table_alias}.contract_address IS NOT NULL "
        f"AND trim({table_alias}.contract_address) != '' "
        f"THEN lower(trim({table_alias}.contract_address)) "
        f"ELSE 'native:' || {table_alias}.asset END"
    )


def _create_token_review_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE token_review (
            wallet_id        INTEGER NOT NULL REFERENCES wallets(id) ON DELETE CASCADE,
            chain            TEXT    NOT NULL,
            token_key        TEXT    NOT NULL,
            asset            TEXT    NOT NULL,
            contract_address TEXT,
            accepted         INTEGER NOT NULL DEFAULT 0,
            review_status    TEXT    NOT NULL DEFAULT 'unknown',
            review_reason    TEXT    NOT NULL DEFAULT 'Nog onvoldoende metadata',
            decision_source  TEXT    NOT NULL DEFAULT 'auto',
            decision_updated_at TEXT,
            valuation_status TEXT    NOT NULL DEFAULT 'active',
            valuation_effective_date TEXT,
            valuation_reason TEXT,
            PRIMARY KEY (wallet_id, chain, token_key)
        );
    """)


def _migrate_token_review_contract_keys(conn: sqlite3.Connection) -> None:
    """
    Rebuild old asset-keyed token_review rows from transactions.

    Existing token choices predate explicit user-vs-auto decisions, so they are
    treated as provisional. Call core.token_review.reclassify_all_token_reviews()
    explicitly after init_db() when smart defaults should be applied.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='token_review'"
    ).fetchone()
    if not row:
        return

    cols = [r[1] for r in conn.execute("PRAGMA table_info(token_review)").fetchall()]
    if "token_key" in cols:
        for col, ddl in (
            ("review_status", "ALTER TABLE token_review ADD COLUMN review_status TEXT NOT NULL DEFAULT 'unknown'"),
            ("review_reason", "ALTER TABLE token_review ADD COLUMN review_reason TEXT NOT NULL DEFAULT 'Nog onvoldoende metadata'"),
            ("decision_source", "ALTER TABLE token_review ADD COLUMN decision_source TEXT NOT NULL DEFAULT 'auto'"),
            ("decision_updated_at", "ALTER TABLE token_review ADD COLUMN decision_updated_at TEXT"),
            ("valuation_status", "ALTER TABLE token_review ADD COLUMN valuation_status TEXT NOT NULL DEFAULT 'active'"),
            ("valuation_effective_date", "ALTER TABLE token_review ADD COLUMN valuation_effective_date TEXT"),
            ("valuation_reason", "ALTER TABLE token_review ADD COLUMN valuation_reason TEXT"),
        ):
            if col not in cols:
                conn.execute(ddl)
        return

    conn.execute("ALTER TABLE token_review RENAME TO _token_review_old")
    _create_token_review_table(conn)
    token_key_expr = _token_key_sql("t")
    conn.execute(
        f"""
        INSERT OR IGNORE INTO token_review
            (wallet_id, chain, token_key, asset, contract_address, accepted)
        SELECT
            t.wallet_id,
            t.chain,
            {token_key_expr} AS token_key,
            MIN(t.asset) AS asset,
            CASE
                WHEN MAX(CASE WHEN t.contract_address IS NOT NULL AND t.contract_address != '' THEN 1 ELSE 0 END) = 1
                THEN lower(MAX(t.contract_address))
                ELSE NULL
            END AS contract_address,
            0 AS accepted
        FROM transactions t
        GROUP BY t.wallet_id, t.chain, token_key
        """
    )
    conn.execute("DROP TABLE _token_review_old")


def _migrate_token_public_evidence(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS token_public_evidence (
            chain            TEXT    NOT NULL,
            contract_address TEXT    NOT NULL,
            source           TEXT    NOT NULL,
            status           TEXT    NOT NULL,
            name             TEXT,
            symbol           TEXT,
            reason           TEXT,
            payload_json     TEXT,
            fetched_at       TEXT    NOT NULL,
            PRIMARY KEY (chain, contract_address, source)
        );

        CREATE TABLE IF NOT EXISTS token_source_cache (
            source     TEXT NOT NULL,
            chain      TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (source, chain)
        );
    """)


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_SQL)
        _migrate_wallet_chain_state(conn)
        _migrate_tx_dedup_constraint(conn)
        _migrate_tx_address_columns(conn)
        _migrate_tx_method_columns(conn)
        _migrate_token_review_contract_keys(conn)
        _migrate_token_public_evidence(conn)
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


def transaction_count() -> int:
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
