"""
Token review: scam detection, metadata enrichment, acceptance management.
"""

import re as _re
import time
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from core.db import get_connection
from core import api
from core.models import (
    CHAINS,
    COINGECKO_TOKEN_LIST_PLATFORMS,
    WETH_CONTRACTS,
    get_staked_info,
    is_known_safe_token_contract,
)
from core.token_identity import identity_contracts_by_asset


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
SOURCE_COINGECKO_LIST = "coingecko_token_list"
SOURCE_COINGECKO_CONTRACT = "coingecko_contract"
SOURCE_COINMARKETCAP_CONTRACT = "coinmarketcap_contract"
SOURCE_GOPLUS = "goplus"
PUBLIC_SOURCE_TTL_DAYS = 7

_CANONICAL_TICKER_CONTRACTS: dict[str, dict[str, set[str]]] = {
    "USDC": {
        "ethereum": {"0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"},
        "arbitrum": {"0xaf88d065e77c8cc2239327c5edb3a432268e5831"},
        "base": {"0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
        "optimism": {"0x0b2c639c533813f4aa9d7837caf62653d097ff85"},
        "polygon": {"0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"},
    },
    "USDT": {
        "ethereum": {"0xdac17f958d2ee523a2206206994597c13d831ec7"},
        "arbitrum": {"0xfd086bc7cd5c481dcc9c85ebe478a1c0b69fcbb9"},
        "optimism": {"0x94b008aa00579c1307b0ef2c499ad98a8ce58e58"},
        "polygon": {"0xc2132d05d31c914a87c6611c10748aeb04b58e8f"},
    },
    "DAI": {
        "ethereum": {"0x6b175474e89094c44da98b954eedeac495271d0f"},
        "arbitrum": {"0xda10009cbd5d07dd0cecc66161fc93d7c9000da1"},
        "optimism": {"0xda10009cbd5d07dd0cecc66161fc93d7c9000da1"},
        "polygon": {"0x8f3cf7ad23cd3cadbd9735aff958023239c6a063"},
    },
    "WBTC": {
        "ethereum": {"0x2260fac5e5542a773aa44fbcfedf7c193bc2c599"},
        "arbitrum": {"0x2f2a2543b76a4166549f7aab2e75bef0aefc5b0f"},
        "optimism": {"0x68f180fcce6836688e9084f035309e29bf0a2095"},
        "polygon": {"0x1bfd67037b42cf73acf2047067bd4f2c47d9bfd6"},
    },
    "WETH": {
        chain: {contract.lower()}
        for chain, contract in WETH_CONTRACTS.items()
    },
}
for _asset, _chains in identity_contracts_by_asset().items():
    target = _CANONICAL_TICKER_CONTRACTS.setdefault(_asset, {})
    for _chain, _contracts in _chains.items():
        target.setdefault(_chain, set()).update(_contracts)

_KNOWN_DEX_ROUTERS: dict[str, dict[str, str]] = {
    "ethereum": {
        "0x7a250d5630b4cf539739df2c5dacabcc4d8d60d": "Uniswap V2 Router",
        "0xe592427a0aece92de3edee1f18e0157c05861564": "Uniswap V3 SwapRouter",
        "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45": "Uniswap V3 SwapRouter02",
        "0xef1c6e67703c7bd7107eed8303fbe6ec2554bf6b": "Uniswap Universal Router",
        "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad": "Uniswap Universal Router",
        "0x66a9893cc07d91d95644aedd05d03f95e1dba8af": "Uniswap Universal Router",
        "0x4c82d1fbfe28c977cbb58d8c7ff8fcf9f70a2cca": "Uniswap Universal Router",
    },
    "arbitrum": {
        "0xa51afafe0263b40edaef0df8781ea9aa03e381a3": "Uniswap Universal Router",
        "0x8b844f885672f333bc0042cb669255f93a4c1e6b": "Uniswap Universal Router",
    },
    "base": {
        "0x6ff5693b99212da76ad316178a184ab56d299b43": "Uniswap Universal Router",
        "0xfdf682f51fe81aa4898f0ae2163d8a55c127fbc7": "Uniswap Universal Router",
    },
    "optimism": {
        "0x851116d9223fabed8e56c0e6b8ad0c31d98b3507": "Uniswap Universal Router",
        "0x8b844f885672f333bc0042cb669255f93a4c1e6b": "Uniswap Universal Router",
    },
    "polygon": {
        "0x1095692a6237d83c6a72f3f5efedb9a670c49223": "Uniswap Universal Router",
        "0x8b844f885672f333bc0042cb669255f93a4c1e6b": "Uniswap Universal Router",
    },
}


@dataclass(frozen=True)
class TokenClassification:
    status: str
    reason: str
    accepted_by_default: bool


@dataclass(frozen=True)
class PublicEvidence:
    source: str
    status: str
    reason: str
    name: str | None = None
    symbol: str | None = None


INTAKE_REVIEW = "review"
INTAKE_NOISE = "noise"
INTAKE_IMPORT = "import"
INTAKE_HIDDEN = "hidden"


@dataclass(frozen=True)
class TokenIntakeGuidance:
    bucket: str
    label: str
    action: str
    why: str
    priority: int


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


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_fresh(value: str | None, days: int = PUBLIC_SOURCE_TTL_DAYS) -> bool:
    fetched = _parse_utc(value)
    if not fetched:
        return False
    return datetime.now(timezone.utc) - fetched < timedelta(days=days)


def token_key(asset: str, contract_address: str | None) -> str:
    """Stable token-review key: contract for ERC-20, native symbol for native rows."""
    contract = (contract_address or "").strip().lower()
    if contract:
        return contract
    return f"native:{asset}"


def token_key_sql(tx_alias: str = "t") -> str:
    return (
        f"CASE WHEN {tx_alias}.contract_address IS NOT NULL "
        f"AND trim({tx_alias}.contract_address) != '' "
        f"THEN lower(trim({tx_alias}.contract_address)) "
        f"ELSE 'native:' || {tx_alias}.asset END"
    )


def token_review_join_condition(tx_alias: str = "t", review_alias: str = "tr") -> str:
    return (
        f"{review_alias}.wallet_id = {tx_alias}.wallet_id "
        f"AND {review_alias}.chain = {tx_alias}.chain "
        f"AND {review_alias}.token_key = {token_key_sql(tx_alias)}"
    )


def _evidence_from_rows(rows: list[dict]) -> list[PublicEvidence]:
    return [
        PublicEvidence(
            source=r.get("source", ""),
            status=r.get("status", ""),
            reason=r.get("reason", "") or "",
            name=r.get("name"),
            symbol=r.get("symbol"),
        )
        for r in rows
    ]


def _public_evidence(token: dict) -> list[PublicEvidence]:
    raw = token.get("public_evidence") or []
    evidence: list[PublicEvidence] = []
    for item in raw:
        if isinstance(item, PublicEvidence):
            evidence.append(item)
        elif isinstance(item, dict):
            evidence.append(PublicEvidence(
                source=item.get("source", ""),
                status=item.get("status", ""),
                reason=item.get("reason", "") or "",
                name=item.get("name"),
                symbol=item.get("symbol"),
            ))
    return evidence


def _first_evidence(evidence: list[PublicEvidence], *statuses: str) -> PublicEvidence | None:
    wanted = set(statuses)
    for item in evidence:
        if item.status in wanted:
            return item
    return None


def _first_public_known_evidence(evidence: list[PublicEvidence]) -> PublicEvidence | None:
    known_sources = {
        SOURCE_COINGECKO_LIST,
        SOURCE_COINGECKO_CONTRACT,
        SOURCE_COINMARKETCAP_CONTRACT,
    }
    for item in evidence:
        if item.status == STATUS_SAFE and item.source in known_sources:
            return item
    return None


def _ticker_impersonation_reason(chain: str, asset: str, contract_address: str | None) -> str | None:
    if not contract_address:
        return None
    symbol = (asset or "").strip().upper()
    canonical_contracts = _CANONICAL_TICKER_CONTRACTS.get(symbol, {}).get(chain)
    if not canonical_contracts:
        return None
    if contract_address.lower() in canonical_contracts:
        return None

    label = CHAINS.get(chain, {}).get("label", chain)
    return f"Ticker lijkt op {symbol}, maar contract is niet het bekende {symbol}-contract op {label}"


def _dex_router_condition_sql(alias: str = "action") -> str:
    clauses = []
    for chain, routers in _KNOWN_DEX_ROUTERS.items():
        addresses = ", ".join(f"'{address}'" for address in routers)
        clauses.append(f"({alias}.chain = '{chain}' AND lower({alias}.to_address) IN ({addresses}))")
    return "(" + " OR ".join(clauses) + ")"


def classify_token(token: dict) -> TokenClassification:
    """Classify a token-review row using name, contract allowlist and metadata."""
    chain = token.get("chain", "")
    asset = token.get("asset", "")
    contract = (token.get("contract_address") or "").strip().lower() or None
    evidence = _public_evidence(token)

    if is_scam(asset):
        return TokenClassification(
            STATUS_SCAM,
            "Scam-naam bevat URL/claim of verdacht patroon",
            False,
        )

    hard_risk = _first_evidence(evidence, STATUS_SCAM)
    if hard_risk:
        return TokenClassification(STATUS_SCAM, hard_risk.reason or "Publieke security-bron markeert token als high-risk", False)

    if contract is None and asset == CHAINS.get(chain, {}).get("native"):
        return TokenClassification(STATUS_SAFE, "Native chain-token", True)

    staked_info = get_staked_info(chain, asset)
    if staked_info:
        expected = (staked_info.get("wrapper_contract") or staked_info["staking_contract"]).lower()
        if contract and contract != expected:
            return TokenClassification(
                STATUS_SUSPICIOUS,
                f"Ticker lijkt op {asset}, maar contract is niet de bekende staking-wrapper",
                False,
            )
        return TokenClassification(STATUS_SAFE, "Bekende staking-wrapper", True)

    if is_known_safe_token_contract(chain, contract):
        return TokenClassification(STATUS_SAFE, "Bekend veilig contract", True)

    impersonation_reason = _ticker_impersonation_reason(chain, asset, contract)
    if impersonation_reason:
        return TokenClassification(STATUS_SUSPICIOUS, impersonation_reason, False)

    public_known = _first_public_known_evidence(evidence)
    if public_known:
        return TokenClassification(STATUS_SAFE, public_known.reason or "Publiek bekende token", True)

    if token.get("has_metadata"):
        if token.get("verified"):
            return TokenClassification(STATUS_SAFE, "Etherscan verified token", True)
        if is_suspicious_by_metadata(token):
            return TokenClassification(
                STATUS_SUSPICIOUS,
                "Geen verificatie, website of socials",
                False,
            )

    soft_risk = _first_evidence(evidence, STATUS_SUSPICIOUS)
    if soft_risk:
        return TokenClassification(STATUS_SUSPICIOUS, soft_risk.reason or "Publieke security-bron ziet risicosignalen", False)

    return TokenClassification(STATUS_UNKNOWN, "Geen publieke bronmatch", False)


def _as_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _reason_text(token: dict, fallback: str) -> str:
    reason = (token.get("review_reason") or "").strip()
    return reason.rstrip(".") if reason else fallback


def token_intake_guidance(token: dict) -> TokenIntakeGuidance:
    """
    Product-facing intake layer on top of the technical classifier.

    The classifier answers "what evidence do we have?". This helper answers
    "what should a human do next?" without changing auditability: all
    transactions remain stored, and accepted stays the portfolio gate.
    """
    status = token.get("review_status") or STATUS_UNKNOWN
    reason = _reason_text(token, "Nog onvoldoende bewijs")
    tx_count = _as_int(token.get("tx_count"))
    in_count = _as_int(token.get("in_count"))
    out_count = _as_int(token.get("out_count"))
    wallet_count = _as_int(token.get("wallet_count"))
    net_amount = _as_float(token.get("net_amount"))
    self_initiated_swap_count = _as_int(token.get("self_initiated_swap_count"))
    bulk_airdrop_count = _as_int(token.get("bulk_airdrop_count"))

    only_inbound = in_count > 0 and out_count == 0
    own_activity = out_count > 0
    repeated_or_shared = tx_count > 1 or wallet_count > 1
    has_net_balance = net_amount > 0
    self_initiated_swap = self_initiated_swap_count > 0

    if token.get("decision_source") == USER_DECISION and not token.get("accepted"):
        return TokenIntakeGuidance(
            INTAKE_HIDDEN,
            "Verborgen",
            "Handmatig afgewezen",
            f"Door gebruiker uit portfolio gehouden. Technisch signaal blijft zichtbaar: {reason}.",
            5,
        )

    if status == STATUS_SAFE:
        return TokenIntakeGuidance(
            INTAKE_IMPORT,
            "Importeren",
            "Aangevinkt laten",
            f"Betrouwbaar genoeg voor import: {reason}.",
            90,
        )

    if token.get("accepted"):
        return TokenIntakeGuidance(
            INTAKE_IMPORT,
            "Importeren",
            "Handmatig geaccepteerd",
            f"Door gebruiker geaccepteerd voor portfolio. Technisch signaal blijft zichtbaar: {reason}.",
            85,
        )

    if status == STATUS_SCAM:
        return TokenIntakeGuidance(
            INTAKE_HIDDEN,
            "Verborgen",
            "Verborgen laten",
            f"Duidelijk afwijzen: {reason}.",
            0,
        )

    if self_initiated_swap and status == STATUS_SUSPICIOUS:
        return TokenIntakeGuidance(
            INTAKE_REVIEW,
            "Twijfel-lijst",
            "Controleren voor import",
            f"Deze token kwam binnen via een door de wallet gestarte DEX-swap, maar er is ook een risicosignaal: {reason}.",
            30,
        )

    if self_initiated_swap:
        return TokenIntakeGuidance(
            INTAKE_REVIEW,
            "Twijfel-lijst",
            "Waarschijnlijk importeren",
            "Deze token kwam binnen via een door de wallet gestarte DEX-swap. Dat is geen passieve airdrop; controleer kort of je deze swap herkent.",
            35,
        )

    if bulk_airdrop_count > 0 and only_inbound:
        return TokenIntakeGuidance(
            INTAKE_HIDDEN,
            "Verborgen",
            "Waarschijnlijk phishing-airdrop",
            "Deze token kwam alleen binnen via een bulk-transfer naar meerdere adressen. Dat past bij spam/phishing-airdrops; laat verborgen tenzij je dit project herkent.",
            15,
        )

    if only_inbound and status == STATUS_SUSPICIOUS:
        return TokenIntakeGuidance(
            INTAKE_NOISE,
            "Waarschijnlijk ruis",
            "Uitgevinkt laten",
            f"Zwakke metadata of risicosignaal en alleen passief ontvangen: {reason}.",
            10,
        )

    if only_inbound and status == STATUS_UNKNOWN:
        return TokenIntakeGuidance(
            INTAKE_NOISE,
            "Waarschijnlijk ruis",
            "Alleen importeren als je dit herkent",
            "Geen publieke match en alleen inkomend ontvangen. Dit lijkt vaak op een airdrop; onbekend is niet automatisch scam.",
            20,
        )

    if status == STATUS_SUSPICIOUS:
        if own_activity or has_net_balance:
            why = "Er is een risicosignaal, maar ook eigen activiteit of saldo. Open de recente transacties en het contract voordat je importeert."
        else:
            why = f"Er is een risicosignaal: {reason}. Controleer het contract voordat je importeert."
        return TokenIntakeGuidance(
            INTAKE_REVIEW,
            "Twijfel-lijst",
            "Handmatig controleren",
            why,
            40,
        )

    if own_activity:
        return TokenIntakeGuidance(
            INTAKE_REVIEW,
            "Twijfel-lijst",
            "Handmatig controleren",
            "Geen publieke match, maar je wallet heeft uitgaande activiteit. Controleer of dit een echte positie is.",
            60,
        )

    if repeated_or_shared or has_net_balance:
        return TokenIntakeGuidance(
            INTAKE_REVIEW,
            "Twijfel-lijst",
            "Kort controleren",
            "Geen publieke match, maar er is herhaalde activiteit, meerdere wallets of saldo. Controleer het contract kort.",
            70,
        )

    return TokenIntakeGuidance(
        INTAKE_REVIEW,
        "Twijfel-lijst",
        "Handmatig controleren",
        "Geen publieke match. Onbekend is niet automatisch scam; controleer contract en recente transacties.",
        50,
    )


def token_intake_sort_key(token: dict) -> tuple:
    guidance = token_intake_guidance(token)
    return (
        guidance.priority,
        -_as_int(token.get("tx_count")),
        token.get("chain") or "",
        token.get("asset") or "",
        token.get("token_key") or "",
    )


# ---------------------------------------------------------------------------
# Token review queries
# ---------------------------------------------------------------------------

_USER_DEX_ACTION_EXISTS_SQL = f"""
    EXISTS (
        SELECT 1
        FROM transactions action
        JOIN wallets action_wallet ON action_wallet.id = action.wallet_id
        WHERE action.wallet_id = t.wallet_id
          AND action.chain = t.chain
          AND substr(action.tx_hash, 1, 66) = substr(t.tx_hash, 1, 66)
          AND action.source = 'txlist'
          AND lower(action.from_address) = lower(action_wallet.address)
          AND (
              {_dex_router_condition_sql("action")}
              OR lower(COALESCE(action.method_name, '')) LIKE '%swap%'
          )
    )
"""

_BULK_AIRDROP_METHOD_SQL = """
    (
        lower(COALESCE(t.method_name, '')) LIKE '%address[]%'
        OR lower(COALESCE(t.method_name, '')) LIKE '% dsts%'
        OR lower(COALESCE(t.method_name, '')) LIKE '%recipients%'
        OR lower(COALESCE(t.method_name, '')) LIKE '%airdrop%'
        OR lower(COALESCE(t.method_name, '')) LIKE '%multisend%'
        OR lower(COALESCE(t.method_name, '')) LIKE '%multi send%'
    )
"""

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
        rows = conn.execute(f"""
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
                MAX(tr.valuation_status)      AS valuation_status,
                MAX(tr.valuation_effective_date) AS valuation_effective_date,
                MAX(tr.valuation_reason)      AS valuation_reason,
                MAX(tm.verified)             AS verified,
                MAX(tm.holder_count)         AS holder_count,
                MAX(tm.has_website)          AS has_website,
                MAX(tm.has_social)           AS has_social,
                MAX(CASE WHEN tm.fetched_at IS NOT NULL THEN 1 ELSE 0 END) AS has_metadata,
                COUNT(t.id)                  AS tx_count,
                SUM(CASE WHEN CAST(t.amount AS REAL) > 0 THEN 1 ELSE 0 END) AS in_count,
                SUM(CASE WHEN CAST(t.amount AS REAL) < 0 THEN 1 ELSE 0 END) AS out_count,
                MIN(t.timestamp)             AS first_seen,
                MAX(t.timestamp)             AS last_seen,
                SUM(CAST(t.amount AS REAL))  AS net_amount,
                COUNT(DISTINCT CASE
                    WHEN {_USER_DEX_ACTION_EXISTS_SQL}
                    THEN substr(t.tx_hash, 1, 66)
                END) AS self_initiated_swap_count,
                COUNT(DISTINCT CASE
                    WHEN t.source = 'tokentx'
                     AND CAST(t.amount AS REAL) > 0
                     AND {_BULK_AIRDROP_METHOD_SQL}
                    THEN substr(t.tx_hash, 1, 66)
                END) AS bulk_airdrop_count
            FROM token_review tr
            LEFT JOIN transactions t
                ON t.wallet_id = tr.wallet_id
               AND t.chain = tr.chain
               AND tr.token_key = {token_key_sql("t")}
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
                t.source,
                t.method_name
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


# ---------------------------------------------------------------------------
# Public-source evidence cache
# ---------------------------------------------------------------------------

def _save_public_evidence(
    conn,
    chain: str,
    contract_address: str,
    source: str,
    status: str,
    reason: str,
    *,
    name: str | None = None,
    symbol: str | None = None,
    payload: dict | None = None,
    fetched_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO token_public_evidence
            (chain, contract_address, source, status, name, symbol, reason, payload_json, fetched_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(chain, contract_address, source) DO UPDATE SET
            status=excluded.status,
            name=excluded.name,
            symbol=excluded.symbol,
            reason=excluded.reason,
            payload_json=excluded.payload_json,
            fetched_at=excluded.fetched_at
        """,
        (
            chain,
            contract_address.lower(),
            source,
            status,
            name,
            symbol,
            reason,
            json.dumps(payload or {}, sort_keys=True),
            fetched_at or utc_now(),
        ),
    )


def _get_public_evidence_rows(conn, chain: str, contract_address: str | None) -> list[dict]:
    if not contract_address:
        return []
    try:
        rows = conn.execute(
            """
            SELECT source, status, reason, name, symbol, fetched_at
            FROM token_public_evidence
            WHERE chain = ? AND contract_address = ?
            ORDER BY source
            """,
            (chain, contract_address.lower()),
        ).fetchall()
    except Exception:
        return []
    return [dict(r) for r in rows]


def _evidence_source_is_fresh(conn, chain: str, contract_address: str, source: str) -> bool:
    row = conn.execute(
        """
        SELECT fetched_at FROM token_public_evidence
        WHERE chain = ? AND contract_address = ? AND source = ?
        """,
        (chain, contract_address.lower(), source),
    ).fetchone()
    return bool(row and _is_fresh(row["fetched_at"]))


def _source_cache_is_fresh(conn, source: str, chain: str) -> bool:
    row = conn.execute(
        "SELECT fetched_at FROM token_source_cache WHERE source = ? AND chain = ?",
        (source, chain),
    ).fetchone()
    return bool(row and _is_fresh(row["fetched_at"]))


def _mark_source_cache(conn, source: str, chain: str, fetched_at: str) -> None:
    conn.execute(
        """
        INSERT INTO token_source_cache (source, chain, fetched_at)
        VALUES (?, ?, ?)
        ON CONFLICT(source, chain) DO UPDATE SET fetched_at=excluded.fetched_at
        """,
        (source, chain, fetched_at),
    )


def _refresh_coingecko_token_list(conn, chain: str, progress_fn=None) -> int:
    platform = COINGECKO_TOKEN_LIST_PLATFORMS.get(chain)
    if not platform:
        return 0
    if _source_cache_is_fresh(conn, SOURCE_COINGECKO_LIST, chain):
        return 0

    if progress_fn:
        progress_fn(0, f"CoinGecko token list — {chain}")

    data = api.fetch_coingecko_token_list(platform)
    tokens = (data or {}).get("tokens") or []
    chain_id = CHAINS[chain]["chainid"]
    fetched_at = utc_now()
    saved = 0
    for token in tokens:
        if token.get("chainId") != chain_id:
            continue
        address = (token.get("address") or "").strip().lower()
        if not address:
            continue
        _save_public_evidence(
            conn,
            chain,
            address,
            SOURCE_COINGECKO_LIST,
            STATUS_SAFE,
            "CoinGecko token list",
            name=token.get("name"),
            symbol=token.get("symbol"),
            payload={
                "address": address,
                "name": token.get("name"),
                "symbol": token.get("symbol"),
                "decimals": token.get("decimals"),
                "logoURI": token.get("logoURI"),
            },
            fetched_at=fetched_at,
        )
        saved += 1
    _mark_source_cache(conn, SOURCE_COINGECKO_LIST, chain, fetched_at)
    return saved


def _refresh_coingecko_contract(conn, chain: str, contract_address: str) -> int:
    platform = COINGECKO_TOKEN_LIST_PLATFORMS.get(chain)
    if not platform:
        return 0
    contract = contract_address.lower()
    if _evidence_source_is_fresh(conn, chain, contract, SOURCE_COINGECKO_CONTRACT):
        return 0

    data = api.fetch_coingecko_token_data(platform, contract)
    if data and data.get("id"):
        reason = "CoinGecko contract lookup"
        status = STATUS_SAFE
        name = data.get("name")
        symbol = data.get("symbol")
    else:
        reason = "Niet gevonden via CoinGecko contract lookup"
        status = STATUS_UNKNOWN
        name = symbol = None

    _save_public_evidence(
        conn,
        chain,
        contract,
        SOURCE_COINGECKO_CONTRACT,
        status,
        reason,
        name=name,
        symbol=symbol,
        payload=data or {},
    )
    return 1


def _extract_cmc_match(payload: dict, chain: str, contract_address: str) -> dict | None:
    target = contract_address.lower()
    chain_name = CHAINS.get(chain, {}).get("label", "").lower()
    for value in payload.values():
        candidates = value if isinstance(value, list) else [value]
        for coin in candidates:
            if not isinstance(coin, dict):
                continue
            raw_platforms = coin.get("platform") or []
            platforms = raw_platforms if isinstance(raw_platforms, list) else [raw_platforms]
            for platform in platforms:
                if not isinstance(platform, dict):
                    continue
                address = (platform.get("token_address") or "").lower()
                platform_name = (platform.get("name") or "").lower()
                platform_slug = (platform.get("slug") or "").lower()
                if address != target:
                    continue
                if chain_name and chain_name not in {platform_name, platform_slug}:
                    # CMC may use slightly different platform labels; exact
                    # address match is still the important guardrail.
                    pass
                return coin
    return None


def _refresh_coinmarketcap_contract(conn, chain: str, contract_address: str) -> int:
    contract = contract_address.lower()
    if _evidence_source_is_fresh(conn, chain, contract, SOURCE_COINMARKETCAP_CONTRACT):
        return 0

    data = api.fetch_coinmarketcap_token_info(contract)
    coin = _extract_cmc_match(data or {}, chain, contract) if data else None
    if coin:
        status = STATUS_SAFE
        reason = "CoinMarketCap contract metadata"
        name = coin.get("name")
        symbol = coin.get("symbol")
    else:
        status = STATUS_UNKNOWN
        reason = "Niet gevonden via CoinMarketCap contract metadata"
        name = symbol = None

    _save_public_evidence(
        conn,
        chain,
        contract,
        SOURCE_COINMARKETCAP_CONTRACT,
        status,
        reason,
        name=name,
        symbol=symbol,
        payload=data or {},
    )
    return 1


_GOPLUS_HARD_RISK_FIELDS = (
    "is_honeypot",
    "honeypot_with_same_creator",
    "is_blacklisted",
    "malicious_address",
)
_GOPLUS_SOFT_RISK_FIELDS = (
    "is_open_source",
    "is_proxy",
    "is_mintable",
    "can_take_back_ownership",
    "owner_change_balance",
    "hidden_owner",
    "selfdestruct",
    "external_call",
    "transfer_pausable",
    "slippage_modifiable",
    "trading_cooldown",
    "personal_slippage_modifiable",
)


def _goplus_flag(value) -> bool:
    return str(value).strip() == "1"


def _classify_goplus_payload(payload: dict) -> tuple[str, str]:
    hard = [field for field in _GOPLUS_HARD_RISK_FIELDS if _goplus_flag(payload.get(field))]
    if hard:
        return STATUS_SCAM, "GoPlus high-risk: " + ", ".join(hard)

    soft = []
    for field in _GOPLUS_SOFT_RISK_FIELDS:
        value = payload.get(field)
        if field == "is_open_source":
            if str(value).strip() == "0":
                soft.append(field)
        elif _goplus_flag(value):
            soft.append(field)
    if soft:
        return STATUS_SUSPICIOUS, "GoPlus risicosignalen: " + ", ".join(soft[:4])

    return STATUS_SAFE, "GoPlus geen high-risk flags"


def _refresh_goplus_security(conn, chain: str, contract_address: str) -> int:
    chain_id = CHAINS.get(chain, {}).get("chainid")
    if not chain_id:
        return 0
    contract = contract_address.lower()
    if _evidence_source_is_fresh(conn, chain, contract, SOURCE_GOPLUS):
        return 0

    data = api.fetch_goplus_token_security(chain_id, contract)
    if data:
        status, reason = _classify_goplus_payload(data)
        name = data.get("token_name")
        symbol = data.get("token_symbol")
    else:
        status = STATUS_UNKNOWN
        reason = "Geen GoPlus security-data beschikbaar"
        name = symbol = None

    _save_public_evidence(
        conn,
        chain,
        contract,
        SOURCE_GOPLUS,
        status,
        reason,
        name=name,
        symbol=symbol,
        payload=data or {},
    )
    return 1


def _contract_pairs(conn) -> list[tuple[str, str]]:
    rows = conn.execute(
        """
        SELECT DISTINCT chain, lower(contract_address) AS contract_address
        FROM token_review
        WHERE contract_address IS NOT NULL AND contract_address != ''
        ORDER BY chain, contract_address
        """
    ).fetchall()
    return [(r["chain"], r["contract_address"]) for r in rows]


def enrich_public_sources(progress_fn=None) -> tuple[int, int]:
    """
    Populate public evidence for token_review contracts.

    Returns (updated, failed). Failures are intentionally non-fatal: unknown
    tokens stay unknown and get a contract explorer link for manual review.
    """
    conn = get_connection()
    try:
        pairs = _contract_pairs(conn)
        chains = sorted({chain for chain, _ in pairs})
        updated = failed = 0

        for chain in chains:
            try:
                updated += _refresh_coingecko_token_list(conn, chain, progress_fn)
                conn.commit()
            except Exception:
                failed += 1

        total = max(len(pairs), 1)
        for i, (chain, contract) in enumerate(pairs):
            if progress_fn:
                progress_fn(i / total, f"Publieke bronnen — {chain} — {contract[:10]}...")
            try:
                updated += _refresh_coingecko_contract(conn, chain, contract)
                updated += _refresh_coinmarketcap_contract(conn, chain, contract)
                updated += _refresh_goplus_security(conn, chain, contract)
                conn.commit()
            except Exception:
                failed += 1

        if progress_fn:
            progress_fn(1.0, "Klaar")
    finally:
        conn.close()

    reclassify_all_token_reviews()
    return updated, failed


def count_public_enrichable_contracts() -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(DISTINCT contract_address)
            FROM token_review
            WHERE contract_address IS NOT NULL AND contract_address != ''
            """
        ).fetchone()
        return row[0] if row else 0
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
            token["public_evidence"] = _evidence_from_rows(
                _get_public_evidence_rows(conn, token["chain"], token["contract_address"])
            )
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
