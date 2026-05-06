from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from core.db import get_connection


VALUATION_ACTIVE = "active"
VALUATION_UNKNOWN = "unknown"
VALUATION_MANUAL_ZERO = "manual_zero"
VALUATION_WORTHLESS = "worthless"
ZERO_VALUATION_STATUSES = {VALUATION_MANUAL_ZERO, VALUATION_WORTHLESS}
VALID_VALUATION_STATUSES = {
    VALUATION_ACTIVE,
    VALUATION_UNKNOWN,
    VALUATION_MANUAL_ZERO,
    VALUATION_WORTHLESS,
}


@dataclass(frozen=True)
class TokenValuation:
    status: str = VALUATION_ACTIVE
    effective_date: date | None = None
    reason: str = ""


DEFAULT_VALUATION = TokenValuation()


def token_key_for(asset: str | None, contract_address: str | None) -> str:
    contract = (contract_address or "").strip().lower()
    if contract:
        return contract
    return f"native:{asset or ''}"


def valuation_key(chain: str, asset: str | None, contract_address: str | None) -> tuple[str, str]:
    return chain, token_key_for(asset, contract_address)


def valuations_for_keys(keys: set[tuple[str, str]]) -> dict[tuple[str, str], TokenValuation]:
    result = {key: DEFAULT_VALUATION for key in keys}
    if not keys:
        return result

    conn = get_connection()
    try:
        for chain, key in keys:
            rows = conn.execute(
                """
                SELECT valuation_status, valuation_effective_date, valuation_reason
                FROM token_review
                WHERE chain = ? AND token_key = ?
                """,
                (chain, key),
            ).fetchall()
            result[(chain, key)] = _merge_valuation_rows(rows)
    finally:
        conn.close()
    return result


def zero_valuation_applies(valuation: TokenValuation, target_date: date | None) -> bool:
    if valuation.status not in ZERO_VALUATION_STATUSES:
        return False
    if valuation.effective_date is None or target_date is None:
        return True
    return target_date >= valuation.effective_date


def zero_eur_fields(valuation: TokenValuation) -> dict:
    return {
        "eur_price": Decimal("0"),
        "eur_value": Decimal("0"),
        "eur_missing": False,
        "valuation_status": valuation.status,
        "valuation_effective_date": _date_text(valuation.effective_date),
        "valuation_reason": valuation.reason,
        "valuation_manual": True,
    }


def save_global_valuations(selections: list[tuple[str, str, str, str | None, str | None]]) -> None:
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for chain, key, status, effective_date, reason in selections:
            clean_status = _normalize_status(status)
            clean_date = _parse_date(effective_date)
            clean_reason = (reason or "").strip() or None
            conn.execute(
                """
                UPDATE token_review
                SET valuation_status = ?,
                    valuation_effective_date = ?,
                    valuation_reason = ?,
                    decision_updated_at = ?
                WHERE chain = ? AND token_key = ?
                """,
                (clean_status, _date_text(clean_date), clean_reason, now, chain, key),
            )
        conn.commit()
    finally:
        conn.close()


def _merge_valuation_rows(rows) -> TokenValuation:
    valuations = [
        TokenValuation(
            _normalize_status(row["valuation_status"]),
            _parse_date(row["valuation_effective_date"]),
            (row["valuation_reason"] or "").strip(),
        )
        for row in rows
    ]
    for valuation in valuations:
        if valuation.status in ZERO_VALUATION_STATUSES:
            return valuation
    return valuations[0] if valuations else DEFAULT_VALUATION


def _normalize_status(status: str | None) -> str:
    value = (status or VALUATION_ACTIVE).strip()
    if value not in VALID_VALUATION_STATUSES:
        raise ValueError(f"Unknown valuation status: {value}")
    return value


def _parse_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    text = value.strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _date_text(value: date | None) -> str | None:
    return value.isoformat() if value else None
