from typing import Callable

from core.models import get_staked_info
from core.token_review import (
    AUTO_DECISION,
    USER_DECISION,
    classify_token,
    token_key,
    utc_now,
)


def insert_rows(rows: list[dict], wallet_id: int, conn_factory: Callable) -> int:
    """Insert transaction rows and return the exact number inserted."""
    if not rows:
        return 0
    conn = conn_factory()
    try:
        before = conn.total_changes
        conn.executemany(
            """
            INSERT OR IGNORE INTO transactions
              (id, wallet_id, chain, timestamp, block_number, tx_hash,
               from_address, to_address, type, asset, contract_address,
               amount, source, method_id, method_name)
            VALUES
              (:id, :wallet_id, :chain, :timestamp, :block_number, :tx_hash,
               :from_address, :to_address, :type, :asset, :contract_address,
               :amount, :source, :method_id, :method_name)
            """,
            [
                {
                    **row,
                    "wallet_id": wallet_id,
                    "from_address": row.get("from_address"),
                    "to_address": row.get("to_address"),
                    "method_id": row.get("method_id"),
                    "method_name": row.get("method_name"),
                }
                for row in rows
            ],
        )
        conn.commit()
        return conn.total_changes - before
    finally:
        conn.close()


def upsert_token_review(
    wallet_id: int,
    chain: str,
    asset: str,
    contract_address: str | None,
    conn_factory: Callable,
) -> None:
    upsert_token_reviews(wallet_id, [{
        "chain": chain,
        "asset": asset,
        "contract_address": contract_address,
    }], conn_factory)


def upsert_token_reviews(wallet_id: int, rows: list[dict], conn_factory: Callable) -> None:
    """Add unique tokens from parsed transaction rows to token_review."""
    unique: dict[tuple[str, str], dict] = {}
    for row in rows:
        chain = row["chain"]
        asset = row["asset"]
        contract = (row.get("contract_address") or "").lower() or None
        key = token_key(asset, contract)
        unique.setdefault((chain, key), {
            "chain": chain,
            "asset": asset,
            "contract_address": contract,
            "token_key": key,
        })
    if not unique:
        return

    conn = conn_factory()
    try:
        existing_rows = conn.execute(
            """
            SELECT chain, token_key, asset
            FROM token_review
            WHERE wallet_id = ? AND accepted = 1
            """,
            (wallet_id,),
        ).fetchall()
        accepted_keys = {(r["chain"], r["token_key"]) for r in existing_rows}
        accepted_assets = {(r["chain"], r["asset"]) for r in existing_rows}

        now = utc_now()
        prepared = []
        for item in unique.values():
            chain = item["chain"]
            asset = item["asset"]
            contract = item["contract_address"]
            key = item["token_key"]
            classification = classify_token({
                "chain": chain,
                "asset": asset,
                "contract_address": contract,
            })
            auto_accept = 1 if classification.accepted_by_default else 0
            prepared.append((item, classification, auto_accept))
            if auto_accept:
                accepted_keys.add((chain, key))
                accepted_assets.add((chain, asset))

        for idx, (item, classification, auto_accept) in enumerate(prepared):
            chain = item["chain"]
            asset = item["asset"]
            info = get_staked_info(chain, asset)
            if not info:
                continue
            underlying_key = (info.get("underlying_contract") or "").lower()
            if (
                (chain, info["underlying"]) in accepted_assets
                or (underlying_key and (chain, underlying_key) in accepted_keys)
            ):
                auto_accept = 1
                prepared[idx] = (item, classification, auto_accept)
                accepted_keys.add((chain, item["token_key"]))
                accepted_assets.add((chain, asset))

        conn.executemany(
            _TOKEN_REVIEW_UPSERT_SQL,
            [
                (
                    wallet_id,
                    item["chain"],
                    item["token_key"],
                    item["asset"],
                    item["contract_address"],
                    auto_accept,
                    classification.status,
                    classification.reason,
                    AUTO_DECISION,
                    now,
                    USER_DECISION,
                    USER_DECISION,
                    USER_DECISION,
                )
                for item, classification, auto_accept in prepared
            ],
        )

        auto_accepted = [item for item, _classification, auto_accept in prepared if auto_accept]
        if auto_accepted:
            conn.executemany(
                """
                UPDATE token_review
                SET accepted = 1, decision_source = ?, decision_updated_at = ?
                WHERE wallet_id = ?
                  AND chain = ?
                  AND token_key = ?
                  AND decision_source != ?
                """,
                [
                    (AUTO_DECISION, now, wallet_id, item["chain"], item["token_key"], USER_DECISION)
                    for item in auto_accepted
                ],
            )
        conn.commit()
    finally:
        conn.close()


def upsert_token_meta(
    chain: str,
    contract_address: str,
    symbol: str,
    decimals: int,
    last_seen: str,
    conn_factory: Callable,
) -> None:
    if not contract_address:
        return
    conn = conn_factory()
    try:
        conn.execute(
            """
            INSERT INTO token_meta (chain, contract_address, symbol, decimals, last_seen)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chain, contract_address) DO UPDATE SET
                symbol    = excluded.symbol,
                decimals  = excluded.decimals,
                last_seen = excluded.last_seen
            """,
            (chain, contract_address.lower(), symbol, decimals, last_seen),
        )
        conn.commit()
    finally:
        conn.close()


_TOKEN_REVIEW_UPSERT_SQL = """
    INSERT INTO token_review
        (wallet_id, chain, token_key, asset, contract_address, accepted,
         review_status, review_reason, decision_source, decision_updated_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(wallet_id, chain, token_key) DO UPDATE SET
        asset = excluded.asset,
        contract_address = excluded.contract_address,
        review_status = excluded.review_status,
        review_reason = excluded.review_reason,
        accepted = CASE
            WHEN token_review.decision_source = ? THEN token_review.accepted
            ELSE excluded.accepted
        END,
        decision_source = CASE
            WHEN token_review.decision_source = ? THEN token_review.decision_source
            ELSE excluded.decision_source
        END,
        decision_updated_at = CASE
            WHEN token_review.decision_source = ? THEN token_review.decision_updated_at
            ELSE excluded.decision_updated_at
        END
"""
