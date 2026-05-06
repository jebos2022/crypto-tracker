from core.db import get_connection
from core.token_review import token_review_join_condition


def get_transaction_wallets() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, name FROM wallets ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_transaction_chains(wallet_id: int | None) -> list[str]:
    sql = f"""
        SELECT DISTINCT t.chain
        FROM transactions t
        JOIN token_review tr
          ON {token_review_join_condition("t", "tr")}
        WHERE tr.accepted = 1
    """
    params: list = []
    if wallet_id is not None:
        sql += " AND t.wallet_id = ?"
        params.append(wallet_id)
    sql += " ORDER BY t.chain"

    conn = get_connection()
    try:
        return [r["chain"] for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_transaction_years(wallet_id: int | None, chain: str | None) -> list[int]:
    sql = f"""
        SELECT DISTINCT substr(t.timestamp, 1, 4) AS year
        FROM transactions t
        JOIN token_review tr
          ON {token_review_join_condition("t", "tr")}
        WHERE tr.accepted = 1
          AND t.timestamp IS NOT NULL
          AND length(t.timestamp) >= 4
    """
    params: list = []
    if wallet_id is not None:
        sql += " AND t.wallet_id = ?"
        params.append(wallet_id)
    if chain is not None:
        sql += " AND t.chain = ?"
        params.append(chain)
    sql += " ORDER BY year DESC"

    conn = get_connection()
    try:
        years = [r["year"] for r in conn.execute(sql, params).fetchall()]
        return [int(year) for year in years if year and str(year).isdigit()]
    finally:
        conn.close()


def get_transaction_assets(wallet_id: int | None, chain: str | None, year: int | None) -> list[str]:
    sql = f"""
        SELECT DISTINCT t.asset
        FROM transactions t
        JOIN token_review tr
          ON {token_review_join_condition("t", "tr")}
        WHERE tr.accepted = 1
    """
    params: list = []
    if wallet_id is not None:
        sql += " AND t.wallet_id = ?"
        params.append(wallet_id)
    if chain is not None:
        sql += " AND t.chain = ?"
        params.append(chain)
    if year is not None:
        sql += " AND substr(t.timestamp, 1, 4) = ?"
        params.append(str(year))
    sql += " ORDER BY t.asset"

    conn = get_connection()
    try:
        return [r["asset"] for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_transactions(
    wallet_id: int | None,
    chain: str | None,
    year: int | None,
    asset: str | None,
    descending: bool,
) -> list[dict]:
    sql = f"""
        SELECT
            w.name AS wallet,
            t.chain,
            t.timestamp,
            t.block_number,
            t.tx_hash,
            t.from_address,
            t.to_address,
            t.type,
            t.asset,
            t.contract_address,
            t.amount,
            t.source,
            t.method_id,
            t.method_name,
            tr.review_status,
            tr.review_reason,
            MAX(tm.verified) AS verified,
            MAX(tm.holder_count) AS holder_count,
            MAX(tm.has_website) AS has_website,
            MAX(tm.has_social) AS has_social,
            MAX(CASE WHEN tm.fetched_at IS NOT NULL THEN 1 ELSE 0 END) AS has_metadata
        FROM transactions t
        JOIN wallets w ON w.id = t.wallet_id
        JOIN token_review tr
          ON {token_review_join_condition("t", "tr")}
        LEFT JOIN token_metadata tm
          ON tm.chain = t.chain
         AND tm.contract_address = t.contract_address
        WHERE tr.accepted = 1
    """
    params: list = []
    if wallet_id is not None:
        sql += " AND t.wallet_id = ?"
        params.append(wallet_id)
    if chain is not None:
        sql += " AND t.chain = ?"
        params.append(chain)
    if year is not None:
        sql += " AND substr(t.timestamp, 1, 4) = ?"
        params.append(str(year))
    if asset is not None:
        sql += f"""
            AND EXISTS (
                SELECT 1
                FROM transactions asset_t
                JOIN token_review asset_tr
                  ON {token_review_join_condition("asset_t", "asset_tr")}
                WHERE asset_tr.accepted = 1
                  AND asset_t.wallet_id = t.wallet_id
                  AND asset_t.chain = t.chain
                  AND substr(asset_t.tx_hash, 1, 66) = substr(t.tx_hash, 1, 66)
                  AND asset_t.asset = ?
            )
        """
        params.append(asset)
    direction = "DESC" if descending else "ASC"
    sql += """
        GROUP BY
            t.id, w.name, t.chain, t.timestamp, t.block_number, t.tx_hash,
            t.from_address, t.to_address, t.type, t.asset, t.contract_address,
            t.amount, t.source, t.method_id, t.method_name,
            tr.review_status, tr.review_reason
    """
    sql += f" ORDER BY t.timestamp {direction}, t.block_number {direction}, t.id {direction}"

    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
