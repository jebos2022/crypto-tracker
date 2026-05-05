from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from core import coingecko, token_valuation
from core.db import get_connection
from core.models import to_decimal
from core.token_identity import PRICING_STAKE_EVENT, token_identity_for
from core.token_review import token_review_join_condition


def eur_value(
    coingecko_id: str | None,
    amount,
    price_date: date | datetime | str,
) -> Decimal | None:
    if not coingecko_id:
        return None
    price = coingecko.fetch_price(coingecko_id, _as_date(price_date))
    if price is None:
        return None
    return to_decimal(amount) * price


def eur_balances_today(rows: list[dict]) -> list[dict]:
    prepared = [_prepare_row(row, "balance") for row in rows]
    valuations = _valuation_map(prepared)
    today = date.today()
    ids = sorted({
        item["coingecko_id"]
        for item in prepared
        if _needs_market_price(item, valuations, today)
    })
    try:
        prices = coingecko.fetch_current_prices(ids) if ids else {}
    except coingecko.CoinGeckoError:
        prices = {}
    return [_with_eur_fields(item, prices.get(item["coingecko_id"]), valuations, today) for item in prepared]


def eur_transactions(rows: list[dict]) -> list[dict]:
    prepared = [_prepare_tx_row(row) for row in rows]
    valuations = _valuation_map(prepared)
    ranges: dict[tuple[str, int], list[date]] = defaultdict(list)
    for item in prepared:
        if _needs_market_price(item, valuations, item["date"]):
            ranges[(item["coingecko_id"], item["date"].year)].append(item["date"])

    price_maps: dict[tuple[str, int], dict[date, Decimal]] = {}
    for (coingecko_id, year), dates in ranges.items():
        try:
            price_maps[(coingecko_id, year)] = coingecko.fetch_price_range(
                coingecko_id,
                min(dates),
                max(dates),
            )
        except coingecko.CoinGeckoError:
            price_maps[(coingecko_id, year)] = {}

    result = []
    for item in prepared:
        price = None
        if _needs_market_price(item, valuations, item["date"]):
            price = price_maps.get((item["coingecko_id"], item["date"].year), {}).get(item["date"])
        result.append(_with_eur_fields(item, price, valuations, item["date"]))
    return result


def transaction_price_ids(rows: list[dict]) -> list[str]:
    prepared = [_prepare_tx_row(row) for row in rows]
    valuations = _valuation_map(prepared)
    return sorted({
        item["coingecko_id"]
        for item in prepared
        if _needs_market_price(item, valuations, item["date"])
    })


def has_unknown_eur(rows: list[dict]) -> bool:
    return any(row.get("eur_value") is None for row in rows)


def available_years() -> list[int]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT MIN(timestamp) AS first_seen FROM transactions"
        ).fetchone()
    finally:
        conn.close()
    first_seen = rows["first_seen"] if rows else None
    if not first_seen:
        return [date.today().year]
    first_year = _date_from_timestamp(first_seen).year if _date_from_timestamp(first_seen) else date.today().year
    return list(range(first_year, date.today().year + 1))


def balance_at(snapshot_date: date | datetime | str) -> list[dict]:
    target = _as_date(snapshot_date)
    cutoff = target.isoformat() + "T23:59:59"
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT
                w.name AS wallet,
                t.chain,
                t.asset,
                t.contract_address,
                t.amount
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            JOIN token_review tr
              ON {token_review_join_condition("t", "tr")}
            WHERE tr.accepted = 1
              AND t.timestamp <= ?
            """,
            (cutoff,),
        ).fetchall()
    finally:
        conn.close()

    totals: dict[tuple[str, str, str, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
    for row in rows:
        contract = (row["contract_address"] or "").lower() or None
        key = (row["wallet"], row["chain"], row["asset"], contract)
        totals[key] += to_decimal(row["amount"])

    return [
        {
            "wallet": wallet,
            "chain": chain,
            "asset": asset,
            "contract_address": contract,
            "balance": amount,
        }
        for (wallet, chain, asset, contract), amount in sorted(totals.items())
        if amount != 0
    ]


def snapshot_price_ids(year: int) -> list[str]:
    open_date = date(year, 1, 1)
    close_date = date(year, 12, 31)
    open_prepared = [_prepare_row(row, "balance") for row in balance_at(open_date)]
    close_prepared = [_prepare_row(row, "balance") for row in balance_at(close_date)]
    open_valuations = _valuation_map(open_prepared)
    close_valuations = _valuation_map(close_prepared)
    ids = {
        item["coingecko_id"]
        for item in open_prepared
        if _needs_market_price(item, open_valuations, open_date)
    }
    ids |= {
        item["coingecko_id"]
        for item in close_prepared
        if _needs_market_price(item, close_valuations, close_date)
    }
    return sorted(ids)


def snapshot_for_year(year: int) -> list[dict]:
    open_date = date(year, 1, 1)
    close_date = date(year, 12, 31)
    open_prepared = [_prepare_row(row, "balance") for row in balance_at(open_date)]
    close_prepared = [_prepare_row(row, "balance") for row in balance_at(close_date)]
    open_valuations = _valuation_map(open_prepared)
    close_valuations = _valuation_map(close_prepared)
    ids = sorted({
        item["coingecko_id"]
        for item in open_prepared
        if _needs_market_price(item, open_valuations, open_date)
    } | {
        item["coingecko_id"]
        for item in close_prepared
        if _needs_market_price(item, close_valuations, close_date)
    })
    price_maps: dict[str, dict[date, Decimal]] = {}
    for coingecko_id in ids:
        try:
            price_maps[coingecko_id] = coingecko.fetch_price_range(coingecko_id, open_date, close_date)
        except coingecko.CoinGeckoError:
            price_maps[coingecko_id] = {}

    open_rows = _snapshot_rows(open_prepared, open_date, price_maps, open_valuations)
    close_rows = _snapshot_rows(close_prepared, close_date, price_maps, close_valuations)
    keys = sorted(set(open_rows) | set(close_rows))

    result = []
    for key in keys:
        open_row = open_rows.get(key)
        close_row = close_rows.get(key)
        base = open_row or close_row or {}
        open_balance = (open_row or {}).get("balance", Decimal("0"))
        close_balance = (close_row or {}).get("balance", Decimal("0"))
        open_eur = _snapshot_eur_value(open_row, open_balance)
        close_eur = _snapshot_eur_value(close_row, close_balance)
        result.append({
            "wallet": base.get("wallet", key[0]),
            "chain": base.get("chain", key[1]),
            "asset": base.get("asset", key[2]),
            "contract_address": base.get("contract_address", key[3]),
            "coingecko_id": base.get("coingecko_id"),
            "open_balance": open_balance,
            "open_price": (open_row or {}).get("eur_price"),
            "open_eur": open_eur,
            "open_valuation_status": (open_row or {}).get("valuation_status"),
            "open_valuation_reason": (open_row or {}).get("valuation_reason"),
            "close_balance": close_balance,
            "close_price": (close_row or {}).get("eur_price"),
            "close_eur": close_eur,
            "close_valuation_status": (close_row or {}).get("valuation_status"),
            "close_valuation_reason": (close_row or {}).get("valuation_reason"),
            "incomplete": _snapshot_eur_missing(open_row, open_balance)
            or _snapshot_eur_missing(close_row, close_balance),
        })
    return result


def _prepare_tx_row(row: dict) -> dict:
    tx_date = _date_from_timestamp(row.get("timestamp"))
    item = _prepare_row(row, "amount")
    item["date"] = tx_date
    item["can_price"] = item["can_price"] and tx_date is not None
    return item


def _prepare_row(row: dict, amount_key: str) -> dict:
    chain = row.get("chain", "")
    asset = row.get("asset", "")
    contract = row.get("contract_address")
    identity = token_identity_for(chain, contract, asset)
    coingecko_id = None
    canonical_asset = None
    if identity:
        canonical_asset = identity.canonical_asset
        if identity.pricing_policy != PRICING_STAKE_EVENT:
            coingecko_id = identity.coingecko_id
    amount = _pricing_amount(chain, asset, row.get(amount_key, "0"))
    return {
        "row": row,
        "coingecko_id": coingecko_id,
        "canonical_asset": canonical_asset,
        "amount": amount,
        "can_price": coingecko_id is not None and amount is not None,
        "valuation_key": token_valuation.valuation_key(chain, asset, contract),
    }


def _valuation_map(items: list[dict]) -> dict[tuple[str, str], token_valuation.TokenValuation]:
    return token_valuation.valuations_for_keys({item["valuation_key"] for item in items})


def _needs_market_price(
    item: dict,
    valuations: dict[tuple[str, str], token_valuation.TokenValuation],
    price_date: date | None,
) -> bool:
    valuation = valuations.get(item["valuation_key"], token_valuation.DEFAULT_VALUATION)
    return item["can_price"] and not token_valuation.zero_valuation_applies(valuation, price_date)


def _with_eur_fields(
    item: dict,
    price: Decimal | None,
    valuations: dict[tuple[str, str], token_valuation.TokenValuation],
    price_date: date | None,
) -> dict:
    valuation = valuations.get(item["valuation_key"], token_valuation.DEFAULT_VALUATION)
    if token_valuation.zero_valuation_applies(valuation, price_date):
        return {
            **item["row"],
            "coingecko_id": item["coingecko_id"],
            "canonical_asset": item["canonical_asset"],
            **token_valuation.zero_eur_fields(valuation),
        }
    amount = item["amount"]
    eur = None if price is None or amount is None else amount * price
    return {
        **item["row"],
        "coingecko_id": item["coingecko_id"],
        "canonical_asset": item["canonical_asset"],
        "eur_price": price,
        "eur_value": eur,
        "eur_missing": eur is None,
        "valuation_status": valuation.status,
        "valuation_effective_date": valuation.effective_date.isoformat() if valuation.effective_date else None,
        "valuation_reason": valuation.reason,
        "valuation_manual": False,
    }


def _pricing_amount(chain: str, asset: str, amount) -> Decimal | None:
    return to_decimal(amount)


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def _date_from_timestamp(value) -> date | None:
    if not value:
        return None
    try:
        raw = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def _snapshot_rows(
    prepared: list[dict],
    snapshot_date: date,
    price_maps: dict[str, dict[date, Decimal]],
    valuations: dict[tuple[str, str], token_valuation.TokenValuation],
) -> dict[tuple, dict]:
    prices = {
        coingecko_id: values[snapshot_date]
        for coingecko_id, values in price_maps.items()
        if snapshot_date in values
    }
    enriched = [
        _with_eur_fields(item, prices.get(item["coingecko_id"]), valuations, snapshot_date)
        for item in prepared
    ]
    return {
        (row["wallet"], row["chain"], row["asset"], row.get("contract_address")): row
        for row in enriched
    }


def _snapshot_eur_value(row: dict | None, balance: Decimal) -> Decimal | None:
    if to_decimal(balance) == 0:
        return Decimal("0")
    return None if row is None else row.get("eur_value")


def _snapshot_eur_missing(row: dict | None, balance: Decimal) -> bool:
    if to_decimal(balance) == 0:
        return False
    return True if row is None else bool(row.get("eur_missing"))
