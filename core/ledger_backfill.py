from dataclasses import dataclass, field

from core import api
from core.db import get_connection
from core.models import CHAINS
from core.parsers import _address_metadata, _method_metadata


@dataclass
class MethodBackfillSummary:
    scanned: int = 0
    updated: int = 0
    errors: list[str] = field(default_factory=list)


def backfill_transaction_methods(
    wallet_id: int | None = None,
    chain: str | None = None,
    progress_fn=None,
) -> MethodBackfillSummary:
    """
    Fill method_id/method_name for existing txlist rows.

    This does not insert transactions or change balances; it only revisits the
    normal txlist endpoint and updates metadata for matching tx hashes.
    """
    targets = _targets(wallet_id, chain)
    summary = MethodBackfillSummary()
    total = max(len(targets), 1)

    for idx, target in enumerate(targets, start=1):
        wallet_name = target["name"]
        target_chain = target["chain"]
        if progress_fn:
            progress_fn((idx - 1) / total, f"{wallet_name} / {target_chain}")

        try:
            raws = api.fetch_txlist(target["address"], target_chain, startblock=0)
        except Exception as exc:
            summary.errors.append(f"{wallet_name} / {target_chain}: {type(exc).__name__}: {exc}")
            continue

        for raw in raws:
            summary.scanned += 1
            metadata = _method_metadata(raw)
            addresses = _address_metadata(raw)
            if not any(metadata.values()) and not any(addresses.values()):
                continue
            summary.updated += _update_matching_rows(
                target["wallet_id"],
                target_chain,
                raw.get("hash", ""),
                metadata["method_id"],
                metadata["method_name"],
                addresses["from_address"],
                addresses["to_address"],
            )

    if progress_fn:
        progress_fn(1.0, "Klaar")
    return summary


def _targets(wallet_id: int | None, chain: str | None) -> list[dict]:
    sql = """
        SELECT DISTINCT w.id AS wallet_id, w.name, w.address, t.chain
        FROM wallets w
        JOIN transactions t ON t.wallet_id = w.id
        WHERE t.source = 'txlist'
    """
    params: list = []
    if wallet_id is not None:
        sql += " AND w.id = ?"
        params.append(wallet_id)
    if chain is not None:
        sql += " AND t.chain = ?"
        params.append(chain)
    sql += " ORDER BY w.name, t.chain"

    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [
            dict(r) for r in rows
            if r["chain"] in CHAINS and r["address"]
        ]
    finally:
        conn.close()


def _update_matching_rows(
    wallet_id: int,
    chain: str,
    tx_hash: str,
    method_id: str | None,
    method_name: str | None,
    from_address: str | None = None,
    to_address: str | None = None,
) -> int:
    if not tx_hash:
        return 0
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE transactions
               SET method_id = COALESCE(method_id, ?),
                   method_name = COALESCE(method_name, ?),
                   from_address = COALESCE(from_address, ?),
                   to_address = COALESCE(to_address, ?)
             WHERE wallet_id = ?
               AND chain = ?
               AND source = 'txlist'
               AND (tx_hash = ? OR tx_hash LIKE ?)
               AND (
                    method_id IS NULL OR method_name IS NULL
                    OR from_address IS NULL OR to_address IS NULL
               )
            """,
            (method_id, method_name, from_address, to_address, wallet_id, chain, tx_hash, f"{tx_hash}_%"),
        )
        updated = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        return int(updated)
    finally:
        conn.close()
