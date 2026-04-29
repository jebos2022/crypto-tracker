"""
Token review: scam detection, metadata enrichment, acceptance management.
"""

import re as _re
import time
from datetime import datetime, timezone

from core.db import get_connection
from core import api


# ---------------------------------------------------------------------------
# Regex scam detection
# ---------------------------------------------------------------------------

_SCAM_RE = _re.compile(
    r"https?://"
    r"|www\."
    r"|\.(com|io|org|net|xyz|site|tech|app|info|live|lat|eu|gg|cc|store|win|wine|cab|ai)\b"
    r"|t\.ly/|t\s*\.me/|fli\.so/|bio\.link/|wr\.do/"
    r"|\b(claim|visit|airdrop|voucher|verify|reward|drop|redeem|pacificdrop|access|raffle)\b"
    r"|^\$"
    r"|@[a-zA-Z]"
    r"|[Ѐ-ӿ]"
    r"|[԰-֏]"
    r"|[一-鿿]"
    r"|[À-ÖØ-ö]{2,}"
    r"|[ᴀ-ᶿ]"
    r"|\[via ",
    _re.IGNORECASE,
)

_LEGIT_OVERRIDE: set[str] = {"USD Coin"}
_CLEAN_TICKER_RE = _re.compile(r"^[A-Za-z][A-Za-z0-9\-_]{0,19}$")


def is_scam(asset: str) -> bool:
    if asset in _LEGIT_OVERRIDE:
        return False
    return bool(_SCAM_RE.search(asset))


def looks_like_ticker(asset: str) -> bool:
    return bool(_CLEAN_TICKER_RE.match(asset)) and not is_scam(asset)


def is_suspicious_by_metadata(token: dict) -> bool:
    """True if we have metadata and token has zero verification + zero social presence."""
    if not token.get("has_metadata"):
        return False
    return (
        not token.get("verified")
        and not token.get("has_website")
        and not token.get("has_social")
    )


# ---------------------------------------------------------------------------
# Token review queries
# ---------------------------------------------------------------------------

def get_pending_tokens(wallet_id: int | None = None) -> list[dict]:
    conn = get_connection()
    try:
        if wallet_id is not None:
            rows = conn.execute(
                "SELECT tr.*, w.name as wallet_name FROM token_review tr "
                "JOIN wallets w ON w.id = tr.wallet_id "
                "WHERE tr.wallet_id = ? ORDER BY tr.chain, tr.asset",
                (wallet_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT tr.*, w.name as wallet_name FROM token_review tr "
                "JOIN wallets w ON w.id = tr.wallet_id "
                "ORDER BY w.name, tr.chain, tr.asset"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_unique_tokens() -> list[dict]:
    """One row per (chain, asset) with token_metadata joined in."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                tr.chain,
                tr.asset,
                MAX(tr.accepted)             AS accepted,
                COUNT(DISTINCT tr.wallet_id) AS wallet_count,
                MAX(tm.verified)             AS verified,
                MAX(tm.holder_count)         AS holder_count,
                MAX(tm.has_website)          AS has_website,
                MAX(tm.has_social)           AS has_social,
                MAX(CASE WHEN tm.fetched_at IS NOT NULL THEN 1 ELSE 0 END) AS has_metadata
            FROM token_review tr
            LEFT JOIN token_metadata tm
                ON tm.contract_address = tr.contract_address
               AND tm.chain = tr.chain
            GROUP BY tr.chain, tr.asset
            ORDER BY tr.chain, tr.asset
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def set_token_accepted(wallet_id: int, chain: str, asset: str, accepted: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE token_review SET accepted = ? WHERE wallet_id = ? AND chain = ? AND asset = ?",
            (1 if accepted else 0, wallet_id, chain, asset),
        )
        conn.commit()
    finally:
        conn.close()


def set_token_accepted_global(chain: str, asset: str, accepted: bool) -> None:
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE token_review SET accepted = ? WHERE chain = ? AND asset = ?",
            (1 if accepted else 0, chain, asset),
        )
        conn.commit()
    finally:
        conn.close()


def accept_all_tokens() -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE token_review SET accepted = 1")
        conn.commit()
    finally:
        conn.close()


def auto_reject_scams() -> int:
    """Reject all regex-scam tokens. Returns number of rows updated."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT DISTINCT chain, asset FROM token_review").fetchall()
        count = 0
        for r in rows:
            if is_scam(r["asset"]):
                cur = conn.execute(
                    "UPDATE token_review SET accepted = 0 WHERE chain = ? AND asset = ?",
                    (r["chain"], r["asset"]),
                )
                count += cur.rowcount
        conn.commit()
        return count
    finally:
        conn.close()


def accept_non_scams() -> tuple[int, int]:
    """Accept clean tokens; reject regex-scams and metadata-suspicious tokens."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                tr.chain, tr.asset,
                MAX(tm.verified)    AS verified,
                MAX(tm.has_website) AS has_website,
                MAX(tm.has_social)  AS has_social,
                MAX(CASE WHEN tm.fetched_at IS NOT NULL THEN 1 ELSE 0 END) AS has_metadata
            FROM token_review tr
            LEFT JOIN token_metadata tm
                ON tm.contract_address = tr.contract_address
               AND tm.chain = tr.chain
            GROUP BY tr.chain, tr.asset
        """).fetchall()
        accepted = rejected = 0
        for r in rows:
            token = dict(r)
            if is_scam(token["asset"]) or is_suspicious_by_metadata(token):
                conn.execute(
                    "UPDATE token_review SET accepted = 0 WHERE chain = ? AND asset = ?",
                    (token["chain"], token["asset"]),
                )
                rejected += 1
            else:
                conn.execute(
                    "UPDATE token_review SET accepted = 1 WHERE chain = ? AND asset = ?",
                    (token["chain"], token["asset"]),
                )
                accepted += 1
        conn.commit()
        return accepted, rejected
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Token metadata enrichment via Etherscan tokeninfo
# ---------------------------------------------------------------------------

_SOCIAL_FIELDS = (
    "twitter", "telegram", "discord", "github",
    "reddit", "facebook", "wechat", "linkedin", "blog", "email",
)


def _save_token_metadata(chain: str, contract_address: str, info: dict) -> None:
    verified = 1 if str(info.get("blueCheckmark", "")).lower() == "yes" else 0
    has_website = 1 if info.get("website") else 0
    has_social = 1 if any(info.get(f) for f in _SOCIAL_FIELDS) else 0
    holder_count = None
    try:
        hc = str(info.get("holdersCount", "") or "").strip()
        if hc.isdigit():
            holder_count = int(hc)
    except (ValueError, TypeError):
        pass

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO token_metadata
                (contract_address, chain, verified, holder_count, has_website, has_social, fetched_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(contract_address, chain) DO UPDATE SET
                verified=excluded.verified,
                holder_count=excluded.holder_count,
                has_website=excluded.has_website,
                has_social=excluded.has_social,
                fetched_at=excluded.fetched_at
            """,
            (contract_address.lower(), chain, verified, holder_count, has_website, has_social, now),
        )
        conn.commit()
    finally:
        conn.close()


def enrich_tokens(progress_fn=None) -> tuple[int, int]:
    """Fetch tokeninfo for all unique contracts in token_review. Returns (enriched, failed)."""
    conn = get_connection()
    try:
        pairs = conn.execute(
            "SELECT DISTINCT chain, contract_address FROM token_review "
            "WHERE contract_address IS NOT NULL"
        ).fetchall()
    finally:
        conn.close()

    total = len(pairs)
    enriched = failed = 0
    for i, row in enumerate(pairs):
        chain, contract = row["chain"], row["contract_address"]
        if progress_fn:
            progress_fn(i / max(total, 1), f"{chain} — {contract[:10]}…")
        try:
            info = api.fetch_tokeninfo(contract, chain)
            if info:
                _save_token_metadata(chain, contract, info)
                enriched += 1
            else:
                failed += 1
        except Exception:
            failed += 1
        time.sleep(0.25)

    if progress_fn:
        progress_fn(1.0, "Klaar")
    return enriched, failed


def count_enrichable_contracts() -> int:
    """Number of unique contracts that can be enriched via tokeninfo."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT contract_address) FROM token_review "
            "WHERE contract_address IS NOT NULL"
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()
