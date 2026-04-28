"""
Fetch orchestration: parse raw API rows, deduplicate, persist to DB.
Calls core/api.py for HTTP and core/db.py for storage. No HTTP code here.
"""

import uuid
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from core import api
from core.db import get_connection
from core.models import CHAINS, TRANSFER_IN, TRANSFER_OUT, GAS_FEE, to_decimal, to_db


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    wallet_id: int
    chain: str
    new_tx: int = 0
    skipped: int = 0
    max_block: int = 0
    tokens_seen: set[str] = field(default_factory=set)


@dataclass
class FetchSummary:
    results: list[FetchResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_new(self) -> int:
        return sum(r.new_tx for r in self.results)

    @property
    def total_skipped(self) -> int:
        return sum(r.skipped for r in self.results)

    @property
    def all_tokens(self) -> set[str]:
        tokens: set[str] = set()
        for r in self.results:
            tokens |= r.tokens_seen
        return tokens


# ---------------------------------------------------------------------------
# Incremental state helpers
# ---------------------------------------------------------------------------

def _get_last_block(wallet_id: int, chain: str) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT last_block FROM wallet_chain_state WHERE wallet_id = ? AND chain = ?",
            (wallet_id, chain),
        ).fetchone()
        return row["last_block"] if row else 0
    finally:
        conn.close()


def _save_last_block(wallet_id: int, chain: str, last_block: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO wallet_chain_state (wallet_id, chain, last_block, last_fetched)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(wallet_id, chain) DO UPDATE SET
                last_block   = MAX(wallet_chain_state.last_block, excluded.last_block),
                last_fetched = excluded.last_fetched
            """,
            (wallet_id, chain, last_block, now),
        )
        conn.commit()
    finally:
        conn.close()


def _known_hashes(wallet_id: int) -> set[str]:
    """Return tx_hashes already in DB for this wallet (dedup key: tx_hash + wallet_id)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT tx_hash FROM transactions WHERE wallet_id = ? AND tx_hash IS NOT NULL",
            (wallet_id,),
        ).fetchall()
        return {r["tx_hash"] for r in rows}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Row parsers
# ---------------------------------------------------------------------------

def _unix_to_iso(ts_str: str) -> str:
    try:
        dt = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except (ValueError, OSError):
        return ""


def _parse_tokentx_row(raw: dict, wallet: str, chain: str) -> dict | None:
    from_addr = raw.get("from", "").lower()
    to_addr   = raw.get("to",   "").lower()

    if from_addr != wallet and to_addr != wallet:
        return None

    decimals = int(raw.get("tokenDecimal", "18") or "18")
    try:
        amount_raw = Decimal(raw.get("value", "0")) / (Decimal("10") ** decimals)
    except (InvalidOperation, ValueError):
        return None

    direction = TRANSFER_IN if to_addr == wallet else TRANSFER_OUT
    signed = abs(amount_raw) if direction == TRANSFER_IN else -abs(amount_raw)

    return {
        "id":               str(uuid.uuid4()),
        "chain":            chain,
        "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
        "block_number":     int(raw.get("blockNumber", "0") or "0"),
        "tx_hash":          raw.get("hash", ""),
        "type":             direction,
        "asset":            raw.get("tokenSymbol", "").strip(),
        "contract_address": raw.get("contractAddress", "").lower() or None,
        "amount":           to_db(signed),
        "source":           "tokentx",
    }


def _parse_txlist_row(raw: dict, wallet: str, chain: str) -> list[dict]:
    """One txlist row may produce up to two DB rows: value transfer + gas fee."""
    native = CHAINS[chain]["native"]
    from_addr = raw.get("from", "").lower()
    to_addr   = raw.get("to",   "").lower()
    is_error  = raw.get("isError", "0") == "1"
    outer_hash = raw.get("hash", "")
    block_number = int(raw.get("blockNumber", "0") or "0")
    ts = _unix_to_iso(raw.get("timeStamp", "0"))

    rows: list[dict] = []

    # Value transfer — only for successful transactions
    if not is_error:
        value_wei = to_decimal(raw.get("value", "0"))
        if value_wei > 0 and (from_addr == wallet or to_addr == wallet):
            direction = TRANSFER_IN if to_addr == wallet else TRANSFER_OUT
            amount_eth = value_wei / Decimal("10") ** 18
            signed = abs(amount_eth) if direction == TRANSFER_IN else -abs(amount_eth)
            rows.append({
                "id":               str(uuid.uuid4()),
                "chain":            chain,
                "timestamp":        ts,
                "block_number":     block_number,
                "tx_hash":          outer_hash,
                "type":             direction,
                "asset":            native,
                "contract_address": None,
                "amount":           to_db(signed),
                "source":           "txlist",
            })

    # Gas fee — wallet is sender, regardless of success/failure
    if from_addr == wallet:
        gas_used  = to_decimal(raw.get("gasUsed",  "0"))
        gas_price = to_decimal(raw.get("gasPrice", "0"))
        fee = (gas_used * gas_price) / Decimal("10") ** 18
        if fee > 0:
            rows.append({
                "id":               str(uuid.uuid4()),
                "chain":            chain,
                "timestamp":        ts,
                "block_number":     block_number,
                "tx_hash":          outer_hash + "_fee",
                "type":             GAS_FEE,
                "asset":            native,
                "contract_address": None,
                "amount":           to_db(-fee),
                "source":           "txlist",
            })

    return rows


def _parse_internal_row(raw: dict, wallet: str, chain: str, idx: int) -> dict | None:
    """Internal native transfer (DEX swap return, unstake payout, etc.)."""
    if raw.get("isError", "0") == "1":
        return None

    value_wei = to_decimal(raw.get("value", "0"))
    if value_wei == 0:
        return None

    from_addr = raw.get("from", "").lower()
    to_addr   = raw.get("to",   "").lower()

    if from_addr != wallet and to_addr != wallet:
        return None

    native = CHAINS[chain]["native"]
    direction = TRANSFER_IN if to_addr == wallet else TRANSFER_OUT
    amount = value_wei / Decimal("10") ** 18
    signed = abs(amount) if direction == TRANSFER_IN else -abs(amount)
    outer_hash = raw.get("hash", "")

    return {
        "id":               str(uuid.uuid4()),
        "chain":            chain,
        "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
        "block_number":     int(raw.get("blockNumber", "0") or "0"),
        "tx_hash":          f"{outer_hash}_int_{idx}" if outer_hash else f"_int_{idx}",
        "type":             direction,
        "asset":            native,
        "contract_address": None,
        "amount":           to_db(signed),
        "source":           "txlistinternal",
    }


# ---------------------------------------------------------------------------
# Persist helpers
# ---------------------------------------------------------------------------

def _insert_rows(rows: list[dict], wallet_id: int) -> int:
    """Insert rows into transactions. Returns number inserted."""
    if not rows:
        return 0
    conn = get_connection()
    try:
        inserted = 0
        for row in rows:
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO transactions
                      (id, wallet_id, chain, timestamp, block_number, tx_hash,
                       type, asset, contract_address, amount, source)
                    VALUES
                      (:id, :wallet_id, :chain, :timestamp, :block_number, :tx_hash,
                       :type, :asset, :contract_address, :amount, :source)
                    """,
                    {**row, "wallet_id": wallet_id},
                )
                if conn.execute("SELECT changes()").fetchone()[0]:
                    inserted += 1
            except Exception:
                pass
        conn.commit()
        return inserted
    finally:
        conn.close()


def _upsert_token_review(wallet_id: int, chain: str, asset: str, contract_address: str | None) -> None:
    """Add new token to review table if not already known (keeps existing accepted value)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO token_review (wallet_id, chain, asset, contract_address, accepted) "
            "VALUES (?, ?, ?, ?, 0)",
            (wallet_id, chain, asset, contract_address),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------

def fetch_wallet(wallet_id: int, address: str, chain: str) -> FetchResult:
    """Fetch all 3 endpoints for one wallet+chain. Returns FetchResult."""
    addr = address.lower().strip()
    result = FetchResult(wallet_id=wallet_id, chain=chain)

    last_block = _get_last_block(wallet_id, chain)
    startblock = last_block + 1 if last_block > 0 else 0
    known = _known_hashes(wallet_id)

    buffer: list[dict] = []

    def _add(row: dict) -> None:
        h = row.get("tx_hash", "")
        if h and h in known:
            result.skipped += 1
            return
        bn = row.get("block_number", 0)
        if bn > result.max_block:
            result.max_block = bn
        buffer.append(row)
        if h:
            known.add(h)
        result.tokens_seen.add(row["asset"])

    # 1 — ERC-20 transfers
    try:
        for raw in api.fetch_tokentx(addr, chain, startblock):
            parsed = _parse_tokentx_row(raw, addr, chain)
            if parsed:
                _add(parsed)
    except Exception:
        pass

    # 2 — Native transfers + gas fees
    try:
        for raw in api.fetch_txlist(addr, chain, startblock):
            for parsed in _parse_txlist_row(raw, addr, chain):
                _add(parsed)
    except Exception:
        pass

    # 3 — Internal native transfers
    try:
        idx = 0
        for raw in api.fetch_txlistinternal(addr, chain, startblock):
            parsed = _parse_internal_row(raw, addr, chain, idx)
            idx += 1
            if parsed:
                _add(parsed)
    except Exception:
        pass

    # Persist
    result.new_tx = _insert_rows(buffer, wallet_id)

    # Update token_review for newly seen tokens
    for row in buffer:
        _upsert_token_review(wallet_id, chain, row["asset"], row.get("contract_address"))

    # Save incremental state
    if result.max_block > last_block:
        _save_last_block(wallet_id, chain, result.max_block)

    return result


def fetch_all(
    wallets: list[dict],
    chains: list[str] | None = None,
    progress_fn=None,
) -> FetchSummary:
    """
    Fetch all wallets across all chains.

    wallets: list of {"id": int, "address": str, "name": str}
    chains: subset of CHAINS keys, defaults to all
    progress_fn: optional callback(fraction: float, label: str)
    """
    if chains is None:
        chains = list(CHAINS.keys())

    summary = FetchSummary()
    total_steps = len(wallets) * len(chains)
    step = 0

    for wallet in wallets:
        for chain in chains:
            label = CHAINS[chain]["label"]
            addr_short = wallet["address"][:8] + "..."
            if progress_fn:
                progress_fn(
                    step / max(total_steps, 1),
                    f"{label} — {wallet['name']} ({addr_short})",
                )
            step += 1

            try:
                result = fetch_wallet(wallet["id"], wallet["address"], chain)
                summary.results.append(result)
            except Exception as e:
                summary.errors.append(f"{label} / {wallet['name']}: {e}")

            time.sleep(0.15)

    if progress_fn:
        progress_fn(1.0, "Klaar")

    return summary


# ---------------------------------------------------------------------------
# Token review helpers (used by UI)
# ---------------------------------------------------------------------------

def get_pending_tokens(wallet_id: int | None = None) -> list[dict]:
    """Return token_review rows that are not yet accepted (accepted=0)."""
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


def accept_all_tokens() -> None:
    conn = get_connection()
    try:
        conn.execute("UPDATE token_review SET accepted = 1")
        conn.commit()
    finally:
        conn.close()
