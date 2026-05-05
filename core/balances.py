from decimal import Decimal

from core.db import get_connection
from core.models import BRIDGE_IN, BRIDGE_OUT, to_decimal
from core.staking import BEAM_STAKING_CONTRACT
from core.token_identity import PRICING_STAKE_EVENT, token_identity_for
from core.token_review import token_review_join_condition


def get_wallets() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, name FROM wallets ORDER BY name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_balances(wallet_id: int | None = None) -> list[dict]:
    conn = get_connection()
    try:
        sql = f"""
            SELECT
                w.name  AS wallet,
                t.chain,
                t.asset,
                t.contract_address,
                t.amount
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            JOIN token_review tr
              ON {token_review_join_condition("t", "tr")}
            WHERE tr.accepted = 1
        """
        params: list = []
        if wallet_id is not None:
            sql += " AND t.wallet_id = ?"
            params.append(wallet_id)

        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    totals: dict[tuple, Decimal] = {}
    for row in rows:
        contract = (row["contract_address"] or "").lower() or None
        key = (row["wallet"], row["chain"], row["asset"], contract)
        totals[key] = totals.get(key, Decimal("0")) + to_decimal(row["amount"])

    balances = [
        {"wallet": k[0], "chain": k[1], "asset": k[2], "contract_address": k[3], "balance": v}
        for k, v in sorted(totals.items())
    ]
    return balances + get_beam_staking_positions(wallet_id)


def get_beam_staking_positions(wallet_id: int | None = None) -> list[dict]:
    conn = get_connection()
    try:
        sql = f"""
            SELECT
                w.name AS wallet,
                t.amount,
                t.from_address,
                t.to_address
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            JOIN token_review tr
              ON {token_review_join_condition("t", "tr")}
            WHERE tr.accepted = 1
              AND t.chain = 'beam'
              AND t.asset = 'BEAM'
              AND t.type != 'GAS_FEE'
              AND (
                  lower(t.to_address) = ?
                  OR lower(t.from_address) = ?
              )
        """
        params: list = [BEAM_STAKING_CONTRACT, BEAM_STAKING_CONTRACT]
        if wallet_id is not None:
            sql += " AND t.wallet_id = ?"
            params.append(wallet_id)
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()

    return beam_staking_positions_from_rows(rows)


def beam_staking_positions_from_rows(rows: list[dict]) -> list[dict]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        wallet = row["wallet"]
        amount = to_decimal(row.get("amount", "0"))
        from_address = (row.get("from_address") or "").lower()
        to_address = (row.get("to_address") or "").lower()
        if to_address == BEAM_STAKING_CONTRACT and amount < 0:
            totals[wallet] = totals.get(wallet, Decimal("0")) - amount
        elif from_address == BEAM_STAKING_CONTRACT and amount > 0:
            totals[wallet] = totals.get(wallet, Decimal("0")) - amount

    return [
        {
            "wallet": wallet,
            "chain": "beam",
            "asset": "BEAM",
            "display_asset": "BEAM (gestaked)",
            "contract_address": None,
            "balance": amount,
            "balance_kind": "staked",
            "canonical_asset": "BEAM",
        }
        for wallet, amount in sorted(totals.items())
        if amount != 0
    ]


def get_bridge_summary(wallet_id: int | None = None) -> dict[tuple, dict]:
    conn = get_connection()
    try:
        sql = f"""
            SELECT w.name AS wallet, t.chain, t.asset, t.contract_address, t.type, t.amount
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            JOIN token_review tr
              ON {token_review_join_condition("t", "tr")}
            WHERE t.type IN (?, ?)
              AND tr.accepted = 1
        """
        params: list = [BRIDGE_OUT, BRIDGE_IN]
        if wallet_id is not None:
            sql += " AND t.wallet_id = ?"
            params.append(wallet_id)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    summary: dict[tuple, dict] = {}
    for row in rows:
        contract = (row["contract_address"] or "").lower() or None
        key = (row["wallet"], row["chain"], row["asset"], contract)
        entry = summary.setdefault(key, {"out": Decimal("0"), "in": Decimal("0"), "count": 0})
        amount = to_decimal(row["amount"])
        if row["type"] == BRIDGE_OUT:
            entry["out"] += amount
        else:
            entry["in"] += amount
        entry["count"] += 1
    return summary


def summarize_balances(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    summaries: dict[tuple, dict] = {}
    positions = []
    for row in rows:
        enriched = _with_identity(row)
        if enriched["pricing_policy"] == PRICING_STAKE_EVENT:
            positions.append(enriched)
            continue

        key = _summary_key(enriched)
        summary = summaries.setdefault(key, {
            "asset": enriched["canonical_asset"],
            "balance": Decimal("0"),
            "eur_value": Decimal("0"),
            "eur_known": False,
            "eur_missing": False,
            "wallets": set(),
            "chains": set(),
            "tokens": set(),
            "details": [],
        })
        summary["balance"] += to_decimal(enriched.get("balance", "0"))
        if enriched.get("eur_value") is None:
            summary["eur_missing"] = True
        else:
            summary["eur_known"] = True
            summary["eur_value"] += to_decimal(enriched["eur_value"])
        if enriched.get("eur_missing"):
            summary["eur_missing"] = True
        summary["wallets"].add(enriched["wallet"])
        summary["chains"].add(enriched["chain"])
        summary["tokens"].add(enriched["display_asset"])
        summary["details"].append(enriched)

    return (
        sorted(summaries.values(), key=lambda item: item["asset"].upper()),
        sorted(positions, key=lambda item: (item["canonical_asset"].upper(), item["wallet"], item["chain"])),
    )


def _with_identity(row: dict) -> dict:
    identity = token_identity_for(row.get("chain", ""), row.get("contract_address"), row.get("asset"))
    canonical_asset = row.get("canonical_asset") or row.get("asset", "")
    pricing_policy = None
    if identity:
        canonical_asset = identity.canonical_asset
        pricing_policy = identity.pricing_policy
    return {
        **row,
        "canonical_asset": canonical_asset,
        "display_asset": row.get("display_asset") or row.get("asset", ""),
        "pricing_policy": pricing_policy,
    }


def _summary_key(row: dict) -> tuple:
    if row.get("pricing_policy"):
        return ("known", row["canonical_asset"])
    return (
        "unknown",
        row.get("wallet"),
        row.get("chain"),
        row.get("asset"),
        row.get("contract_address"),
    )
