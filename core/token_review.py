"""
Token review: scam detection, metadata enrichment, acceptance management.
"""

import re as _re
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from core.db import get_connection
from core import api
from core.models import CHAINS, get_staked_info, is_known_safe_token_contract


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

STATUS_SAFE = "safe"
STATUS_UNKNOWN = "unknown"
STATUS_SUSPICIOUS = "suspicious"
STATUS_SCAM = "scam"
AUTO_DECISION = "auto"
USER_DECISION = "user"


@dataclass(frozen=True)
class TokenClassification:
    status: str
    reason: str
    accepted_by_default: bool


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


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def token_key(asset: str, contract_address: str | None) -> str:
    """Stable token-review key: contract for ERC-20, native symbol for native rows."""
    contract = (contract_address or "").strip().lower()
    if contract:
        return contract
    return f"native:{asset}"


def token_key_sql(tx_alias: str = "t") -> str:
    return (
        f"CASE WHEN {tx_alias}.contract_address IS NOT NULL "
        f"AND {tx_alias}.contract_address != '' "
        f"THEN lower({tx_alias}.contract_address) "
        f"ELSE 'native:' || {tx_alias}.asset END"
    )


def token_review_join_condition(tx_alias: str = "t", review_alias: str = "tr") -> str:
    return (
        f"{review_alias}.wallet_id = {tx_alias}.wallet_id "
        f"AND {review_alias}.chain = {tx_alias}.chain "
        f"AND {review_alias}.token_key = {token_key_sql(tx_alias)}"
    )


def classify_token(token: dict) -> TokenClassification:
    """Classify a token-review row using name, contract allowlist and metadata."""
    chain = token.get("chain", "")
    asset = token.get("asset", "")
    contract = (token.get("contract_address") or "").strip().lower() or None

    if is_scam(asset):
        return TokenClassification(
            STATUS_SCAM,
            "Scam-naam bevat URL/claim of verdacht patroon",
            False,
        )

    if contract is None and asset == CHAINS.get(chain, {}).get("native"):
        return TokenClassification(STATUS_SAFE, "Native chain-token", True)

    if is_known_safe_token_contract(chain, contract):
        return TokenClassification(STATUS_SAFE, "Bekend veilig contract", True)

    if get_staked_info(chain, asset):
        return TokenClassification(STATUS_SAFE, "Bekende staking-wrapper", True)

    if token.get("has_metadata"):
        if token.get("verified"):
            return TokenClassification(STATUS_SAFE, "Etherscan verified token", True)
        if is_suspicious_by_metadata(token):
            return TokenClassification(
                STATUS_SUSPICIOUS,
                "Geen verificatie, website of socials",
                False,
            )

    return TokenClassification(STATUS_UNKNOWN, "Nog onvoldoende metadata", False)


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
    """One row per contract-aware token key with token_metadata joined in."""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                tr.chain,
                tr.token_key,
                tr.asset,
                MAX(tr.contract_address)     AS contract_address,
                MAX(tr.accepted)             AS accepted,
                COUNT(DISTINCT tr.wallet_id) AS wallet_count,
                MAX(tr.review_status)        AS review_status,
                MAX(tr.review_reason)        AS review_reason,
                MAX(tr.decision_source)       AS decision_source,
                MAX(tm.verified)             AS verified,
                MAX(tm.holder_count)         AS holder_count,
                MAX(tm.has_website)          AS has_website,
                MAX(tm.has_social)           AS has_social,
                MAX(CASE WHEN tm.fetched_at IS NOT NULL THEN 1 ELSE 0 END) AS has_metadata
            FROM token_review tr
            LEFT JOIN token_metadata tm
                ON tm.contract_address = tr.contract_address
               AND tm.chain = tr.chain
            GROUP BY tr.chain, tr.token_key, tr.asset
            ORDER BY tr.chain, tr.asset, tr.token_key
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_token_transactions(chain: str, key: str, limit: int = 5) -> list[dict]:
    """Recent audit rows for one contract-aware token-review item."""
    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            SELECT
                w.name AS wallet,
                t.timestamp,
                t.tx_hash,
                t.asset,
                t.contract_address,
                t.amount,
                t.source
            FROM transactions t
            JOIN wallets w ON w.id = t.wallet_id
            WHERE t.chain = ?
              AND {token_key_sql("t")} = ?
            ORDER BY t.timestamp DESC, t.block_number DESC, t.id DESC
            LIMIT ?
            """,
            (chain, key, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _mark_rows(conn, where_sql: str, params: tuple, accepted: bool, source: str) -> int:
    cur = conn.execute(
        f"""
        UPDATE token_review
        SET accepted = ?, decision_source = ?, decision_updated_at = ?
        WHERE {where_sql}
        """,
        (1 if accepted else 0, source, utc_now(), *params),
    )
    return cur.rowcount


def set_token_accepted(wallet_id: int, chain: str, key: str, accepted: bool) -> None:
    conn = get_connection()
    try:
        count = _mark_rows(
            conn,
            "wallet_id = ? AND chain = ? AND token_key = ?",
            (wallet_id, chain, key),
            accepted,
            USER_DECISION,
        )
        if count == 0:
            _mark_rows(
                conn,
                "wallet_id = ? AND chain = ? AND asset = ?",
                (wallet_id, chain, key),
                accepted,
                USER_DECISION,
            )
        conn.commit()
    finally:
        conn.close()


def set_token_accepted_global(chain: str, key: str, accepted: bool) -> None:
    from core.models import STAKED_TOKENS
    conn = get_connection()
    try:
        count = _mark_rows(
            conn,
            "chain = ? AND token_key = ?",
            (chain, key),
            accepted,
            USER_DECISION,
        )
        if count == 0:
            _mark_rows(
                conn,
                "chain = ? AND asset = ?",
                (chain, key),
                accepted,
                USER_DECISION,
            )
        if accepted:
            # Cascade: auto-accept staked wrappers of this underlying token.
            for staked_asset, info in STAKED_TOKENS.get(chain, {}).items():
                if info["underlying"] == key or info.get("underlying_contract", "").lower() == key.lower():
                    conn.execute(
                        """
                        UPDATE token_review
                        SET accepted = 1,
                            review_status = ?,
                            review_reason = ?,
                            decision_source = ?,
                            decision_updated_at = ?
                        WHERE chain = ? AND asset = ?
                        """,
                        (
                            STATUS_SAFE,
                            "Bekende staking-wrapper",
                            AUTO_DECISION,
                            utc_now(),
                            chain,
                            staked_asset,
                        ),
                    )
        conn.commit()
    finally:
        conn.close()


def save_token_selection_global(selections: list[tuple[str, str, bool]]) -> None:
    """
    Save token-review checkbox edits and then enforce staking wrapper acceptance.

    Writes the full batch first, then runs sync_staking_wrappers() once after
    all checkbox values are persisted — prevents a stale unchecked stPEAR
    checkbox from overwriting a cascade that accepted it via PEAR.
    """
    conn = get_connection()
    try:
        now = utc_now()
        for chain, key, accepted in selections:
            cur = conn.execute(
                """
                UPDATE token_review
                SET accepted = ?, decision_source = ?, decision_updated_at = ?
                WHERE chain = ? AND token_key = ?
                """,
                (1 if accepted else 0, USER_DECISION, now, chain, key),
            )
            if cur.rowcount == 0:
                conn.execute(
                    """
                    UPDATE token_review
                    SET accepted = ?, decision_source = ?, decision_updated_at = ?
                    WHERE chain = ? AND asset = ?
                    """,
                    (1 if accepted else 0, USER_DECISION, now, chain, key),
                )
        conn.commit()
    finally:
        conn.close()

    sync_staking_wrappers()


def sync_staking_wrappers() -> None:
    """Ensure staked wrapper tokens are accepted whenever their underlying is accepted."""
    from core.models import STAKED_TOKENS
    conn = get_connection()
    try:
        now = utc_now()
        for chain, tokens in STAKED_TOKENS.items():
            for staked_asset, info in tokens.items():
                conn.execute(
                    """UPDATE token_review AS st
                       SET accepted = 1,
                           review_status = ?,
                           review_reason = ?,
                           decision_source = ?,
                           decision_updated_at = ?
                       WHERE st.chain = ? AND st.asset = ?
                         AND EXISTS (
                             SELECT 1 FROM token_review AS u
                             WHERE u.wallet_id = st.wallet_id
                               AND u.chain = ?
                               AND (u.asset = ? OR u.token_key = ?)
                               AND u.accepted = 1
                         )""",
                    (
                        STATUS_SAFE,
                        "Bekende staking-wrapper",
                        AUTO_DECISION,
                        now,
                        chain,
                        staked_asset,
                        chain,
                        info["underlying"],
                        info.get("underlying_contract", "").lower(),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def accept_recommended_tokens() -> tuple[int, int]:
    """Accept only safe tokens and reject unknown/suspicious/scam rows."""
    conn = get_connection()
    try:
        now = utc_now()
        cur_accept = conn.execute(
            """
            UPDATE token_review
            SET accepted = 1, decision_source = ?, decision_updated_at = ?
            WHERE review_status = ?
            """,
            (AUTO_DECISION, now, STATUS_SAFE),
        )
        cur_reject = conn.execute(
            """
            UPDATE token_review
            SET accepted = 0, decision_source = ?, decision_updated_at = ?
            WHERE review_status != ?
            """,
            (AUTO_DECISION, now, STATUS_SAFE),
        )
        conn.commit()
        sync_staking_wrappers()
        return cur_accept.rowcount, cur_reject.rowcount
    finally:
        conn.close()


def accept_all_tokens() -> None:
    """Compatibility helper: accept every row as an explicit user decision."""
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE token_review
            SET accepted = 1, decision_source = ?, decision_updated_at = ?
            """,
            (USER_DECISION, utc_now()),
        )
        conn.commit()
    finally:
        conn.close()


def auto_reject_scams() -> int:
    """Reject all classified scam tokens. Returns number of rows updated."""
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE token_review
            SET accepted = 0, decision_source = ?, decision_updated_at = ?
            WHERE review_status = ?
            """,
            (AUTO_DECISION, utc_now(), STATUS_SCAM),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def accept_non_scams() -> tuple[int, int]:
    """Compatibility alias for the recommended portfolio defaults."""
    return accept_recommended_tokens()


def reject_all_tokens() -> int:
    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE token_review
            SET accepted = 0, decision_source = ?, decision_updated_at = ?
            """,
            (USER_DECISION, utc_now()),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def reclassify_all_token_reviews() -> int:
    """
    Refresh review_status/reason for every token.

    Auto decisions follow the classifier defaults. Explicit user decisions keep
    their accepted value, but still receive the latest status and reason.
    """
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                tr.wallet_id,
                tr.chain,
                tr.token_key,
                tr.asset,
                tr.contract_address,
                tr.accepted,
                tr.decision_source,
                MAX(tm.verified) AS verified,
                MAX(tm.has_website) AS has_website,
                MAX(tm.has_social) AS has_social,
                MAX(CASE WHEN tm.fetched_at IS NOT NULL THEN 1 ELSE 0 END) AS has_metadata
            FROM token_review tr
            LEFT JOIN token_metadata tm
                ON tm.contract_address = tr.contract_address
               AND tm.chain = tr.chain
            GROUP BY
                tr.wallet_id, tr.chain, tr.token_key, tr.asset, tr.contract_address,
                tr.accepted, tr.decision_source
        """).fetchall()
        now = utc_now()
        updated = 0
        for row in rows:
            token = dict(row)
            classification = classify_token(token)
            keep_user_choice = token.get("decision_source") == USER_DECISION
            accepted = token["accepted"] if keep_user_choice else int(classification.accepted_by_default)
            conn.execute(
                """
                UPDATE token_review
                SET accepted = ?,
                    review_status = ?,
                    review_reason = ?,
                    decision_source = CASE
                        WHEN decision_source = ? THEN decision_source
                        ELSE ?
                    END,
                    decision_updated_at = CASE
                        WHEN decision_source = ? THEN decision_updated_at
                        ELSE ?
                    END
                WHERE wallet_id = ? AND chain = ? AND token_key = ?
                """,
                (
                    accepted,
                    classification.status,
                    classification.reason,
                    USER_DECISION,
                    AUTO_DECISION,
                    USER_DECISION,
                    now,
                    token["wallet_id"],
                    token["chain"],
                    token["token_key"],
                ),
            )
            updated += 1
        conn.commit()
        sync_staking_wrappers()
        return updated
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

    now = utc_now()
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
    reclassify_all_token_reviews()
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
