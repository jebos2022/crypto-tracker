from collections import defaultdict
from decimal import Decimal

from core.db import get_connection
from core.models import GAS_FEE, to_decimal
from core.prices import eur_transactions, snapshot_for_year, transaction_price_ids
from core.token_review import token_review_join_condition


ZERO = Decimal("0")


def compute_year(year: int) -> list[dict]:
    entries: dict[tuple[str, str, str, str | None], dict] = {}

    for row in snapshot_for_year(year):
        entry = _entry_for(entries, row)
        open_eur, open_missing = _snapshot_eur(row, "open")
        close_eur, close_missing = _snapshot_eur(row, "close")
        entry["open_eur"] = open_eur
        entry["close_eur"] = close_eur
        entry["snapshot_missing"] = open_missing or close_missing

    tx_rows = _transactions_for_year(year)
    for row in eur_transactions(tx_rows) if tx_rows else []:
        entry = _entry_for(entries, row)
        _apply_transaction(entry, row)

    return [
        _finalize(entry)
        for _, entry in sorted(
            entries.items(),
            key=lambda item: (item[0][0].lower(), item[0][1], item[0][2], item[0][3] or ""),
        )
    ]


def price_ids_for_year(year: int) -> list[str]:
    return transaction_price_ids(_transactions_for_year(year))


def _transactions_for_year(year: int) -> list[dict]:
    start = f"{year:04d}-01-01T00:00:00"
    end = f"{year:04d}-12-31T23:59:59"
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT
                t.id,
                w.name AS wallet,
                t.chain,
                t.timestamp,
                t.block_number,
                t.tx_hash,
                t.type,
                t.asset,
                t.contract_address,
                t.amount,
                t.source
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            JOIN token_review tr
              ON {token_review_join_condition("t", "tr")}
            WHERE tr.accepted = 1
              AND t.timestamp >= ?
              AND t.timestamp <= ?
            ORDER BY t.timestamp, t.block_number, t.id
            """,
            (start, end),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def _entry_for(entries: dict, row: dict) -> dict:
    key = _key(row)
    if key not in entries:
        entries[key] = {
            "wallet": key[0],
            "chain": key[1],
            "asset": key[2],
            "contract_address": key[3],
            "open_eur": ZERO,
            "close_eur": ZERO,
            "snapshot_missing": False,
            "in_eur": ZERO,
            "out_eur": ZERO,
            "gas_eur": ZERO,
            "in_missing": False,
            "out_missing": False,
            "gas_missing": False,
        }
    return entries[key]


def _key(row: dict) -> tuple[str, str, str, str | None]:
    contract = (row.get("contract_address") or "").strip().lower() or None
    return row.get("wallet", ""), row.get("chain", ""), row.get("asset", ""), contract


def _snapshot_eur(row: dict, prefix: str) -> tuple[Decimal | None, bool]:
    value = row.get(f"{prefix}_eur")
    if value is not None:
        return value, False
    balance = to_decimal(row.get(f"{prefix}_balance", "0"))
    if balance == 0:
        return ZERO, False
    return None, True


def _apply_transaction(entry: dict, row: dict) -> None:
    amount = to_decimal(row.get("amount", "0"))
    if amount == 0:
        return

    value = row.get("eur_value")
    if row.get("type") == GAS_FEE:
        if value is None:
            entry["gas_missing"] = True
        else:
            entry["gas_eur"] += abs(value)
        return

    if amount > 0:
        _add_value(entry, "in_eur", "in_missing", value)
    elif amount < 0:
        _add_value(entry, "out_eur", "out_missing", value)


def _add_value(entry: dict, bucket: str, missing_bucket: str, value: Decimal | None) -> None:
    if value is None:
        entry[missing_bucket] = True
        return
    entry[bucket] += abs(value)


def _finalize(entry: dict) -> dict:
    in_eur = None if entry["in_missing"] else entry["in_eur"]
    out_eur = None if entry["out_missing"] else entry["out_eur"]
    gas_eur = None if entry["gas_missing"] else entry["gas_eur"]
    incomplete = any([
        entry["snapshot_missing"],
        entry["in_missing"],
        entry["out_missing"],
        entry["gas_missing"],
    ])
    netto_eur = None
    if (
        entry["open_eur"] is not None
        and entry["close_eur"] is not None
        and in_eur is not None
        and out_eur is not None
    ):
        netto_eur = (entry["close_eur"] - entry["open_eur"]) - (in_eur - out_eur)

    return {
        "wallet": entry["wallet"],
        "chain": entry["chain"],
        "asset": entry["asset"],
        "contract_address": entry["contract_address"],
        "open_eur": entry["open_eur"],
        "close_eur": entry["close_eur"],
        "in_eur": in_eur,
        "out_eur": out_eur,
        "gas_eur": gas_eur,
        "netto_eur": netto_eur,
        "incomplete": incomplete,
    }
