"""
Fetch orchestration: parse raw API rows, deduplicate, persist to DB.
Calls core/api.py for HTTP and core/db.py for storage. No HTTP code here.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core import api
from core.db import get_connection
from core.models import (
    CHAINS,
    get_staked_info,
)
from core.parsers import (
    _parse_tokentx_row,
    _parse_txlist_row,
    _parse_internal_row,
)
from core.wrap_reconcile import synthesize_wrap_rows


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class FetchResult:
    wallet_id: int
    chain: str
    new_tx: int = 0
    skipped: int = 0
    # Highest block per endpoint that we successfully fetched.
    # If an endpoint errored we leave it unset so its `last_block` does NOT
    # get advanced — the next fetch will retry from where we stopped.
    max_block_per_endpoint: dict[str, int] = field(default_factory=dict)
    tokens_seen: set[str] = field(default_factory=set)
    endpoint_errors: dict[str, str] = field(default_factory=dict)


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

def _get_last_block(wallet_id: int, chain: str, endpoint: str) -> int:
    """
    Highest block already fetched for (wallet, chain, endpoint).

    Each of `tokentx` / `txlist` / `txlistinternal` is tracked independently
    so a transient failure in one doesn't poison the others' incremental state.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT last_block FROM wallet_chain_state "
            "WHERE wallet_id = ? AND chain = ? AND endpoint = ?",
            (wallet_id, chain, endpoint),
        ).fetchone()
        return row["last_block"] if row else 0
    finally:
        conn.close()


def _save_last_block(wallet_id: int, chain: str, endpoint: str, last_block: int) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO wallet_chain_state (wallet_id, chain, endpoint, last_block, last_fetched)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(wallet_id, chain, endpoint) DO UPDATE SET
                last_block   = MAX(wallet_chain_state.last_block, excluded.last_block),
                last_fetched = excluded.last_fetched
            """,
            (wallet_id, chain, endpoint, last_block, now),
        )
        conn.commit()
    finally:
        conn.close()


def _known_hashes(wallet_id: int) -> set[tuple[str, str]]:
    """Return (tx_hash, source) pairs already in DB for this wallet."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT tx_hash, source FROM transactions WHERE wallet_id = ? AND tx_hash IS NOT NULL",
            (wallet_id,),
        ).fetchall()
        return {(r["tx_hash"], r["source"]) for r in rows}
    finally:
        conn.close()


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
            conn.execute(
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
                {
                    **row,
                    "wallet_id": wallet_id,
                    "from_address": row.get("from_address"),
                    "to_address": row.get("to_address"),
                    "method_id": row.get("method_id"),
                    "method_name": row.get("method_name"),
                },
            )
            if conn.execute("SELECT changes()").fetchone()[0]:
                inserted += 1
        conn.commit()
        return inserted
    finally:
        conn.close()


def _upsert_token_review(wallet_id: int, chain: str, asset: str, contract_address: str | None) -> None:
    """
    Add token to review table if not already known.
    Staked wrapper tokens (xOPN, stPEAR) are auto-accepted when their
    underlying token (OPN, PEAR) is already accepted for this wallet+chain.
    """
    conn = get_connection()
    try:
        info = get_staked_info(chain, asset)
        auto_accept = 0
        if info:
            row = conn.execute(
                "SELECT accepted FROM token_review WHERE wallet_id = ? AND chain = ? AND asset = ?",
                (wallet_id, chain, info["underlying"]),
            ).fetchone()
            if row and row["accepted"]:
                auto_accept = 1

        conn.execute(
            "INSERT OR IGNORE INTO token_review (wallet_id, chain, asset, contract_address, accepted) "
            "VALUES (?, ?, ?, ?, ?)",
            (wallet_id, chain, asset, contract_address, auto_accept),
        )
        if auto_accept:
            # Also flip existing rows that were not yet accepted.
            conn.execute(
                "UPDATE token_review SET accepted = 1 WHERE wallet_id = ? AND chain = ? AND asset = ?",
                (wallet_id, chain, asset),
            )
        conn.commit()
    finally:
        conn.close()


def _upsert_token_meta(chain: str, contract_address: str, symbol: str, decimals: int) -> None:
    """
    Persist per-contract decimals + symbol from raw tokentx rows. Idempotent
    upsert — used later by balance_check to scale on-chain balances.
    """
    if not contract_address:
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    conn = get_connection()
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
            (chain, contract_address.lower(), symbol, decimals, now),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------

def fetch_wallet(wallet_id: int, address: str, chain: str) -> FetchResult:
    """
    Fetch all 3 endpoints for one wallet+chain. Returns FetchResult.

    Each endpoint is fetched independently with its own `last_block` cursor.
    If one endpoint errors, its cursor is NOT advanced — the next fetch will
    retry the same range. The other endpoints still progress normally.
    """
    addr = address.lower().strip()
    result = FetchResult(wallet_id=wallet_id, chain=chain)
    known = _known_hashes(wallet_id)

    buffer: list[dict] = []

    def _add(row: dict, endpoint: str) -> None:
        h = row.get("tx_hash", "")
        key = (h, endpoint)
        if h and key in known:
            result.skipped += 1
            return
        bn = row.get("block_number", 0)
        prev = result.max_block_per_endpoint.get(endpoint, 0)
        if bn > prev:
            result.max_block_per_endpoint[endpoint] = bn
        buffer.append(row)
        if h:
            known.add(key)
        result.tokens_seen.add(row["asset"])

    # Per-endpoint startblock — independent cursors.
    last_blocks = {ep: _get_last_block(wallet_id, chain, ep)
                   for ep in ("tokentx", "txlist", "txlistinternal")}
    startblocks = {ep: (lb + 1 if lb > 0 else 0) for ep, lb in last_blocks.items()}

    # 1 — ERC-20 transfers
    # One transaction can contain multiple Transfer events (e.g. disperseToken).
    # Etherscan returns each as a separate row with the same tx_hash but no logIndex.
    # We suffix duplicate hashes (_dup1, _dup2, ...) so each event gets a unique key.
    try:
        tokentx_hash_counts: dict[str, int] = {}
        meta_seen: dict[str, tuple[str, int]] = {}  # contract -> (symbol, decimals)
        for raw in api.fetch_tokentx(addr, chain, startblocks["tokentx"]):
            parsed = _parse_tokentx_row(raw, addr, chain)
            if parsed:
                h = parsed["tx_hash"]
                count = tokentx_hash_counts.get(h, 0)
                tokentx_hash_counts[h] = count + 1
                if count > 0:
                    parsed["tx_hash"] = f"{h}_dup{count}"
                _add(parsed, "tokentx")
                contract = parsed.get("contract_address")
                if contract and contract not in meta_seen:
                    try:
                        decimals = int(raw.get("tokenDecimal", "18") or "18")
                    except (ValueError, TypeError):
                        decimals = 18
                    meta_seen[contract] = (raw.get("tokenSymbol", "").strip(), decimals)
        for contract, (sym, dec) in meta_seen.items():
            _upsert_token_meta(chain, contract, sym, dec)
    except Exception as e:
        result.endpoint_errors["tokentx"] = f"{type(e).__name__}: {e}"

    # 2 — Native transfers + gas fees
    txlist_rows: list[dict] = []
    try:
        for raw in api.fetch_txlist(addr, chain, startblocks["txlist"]):
            txlist_rows.append(raw)
            for parsed in _parse_txlist_row(raw, addr, chain):
                _add(parsed, "txlist")
    except Exception as e:
        result.endpoint_errors["txlist"] = f"{type(e).__name__}: {e}"

    # 3 — Internal native transfers
    try:
        idx = 0
        for raw in api.fetch_txlistinternal(addr, chain, startblocks["txlistinternal"]):
            parsed = _parse_internal_row(raw, addr, chain, idx)
            idx += 1
            if parsed:
                _add(parsed, "txlistinternal")
    except Exception as e:
        result.endpoint_errors["txlistinternal"] = f"{type(e).__name__}: {e}"

    # 4 — Native-wrap reconciliation (see core/wrap_reconcile.py)
    for synth in synthesize_wrap_rows(buffer, txlist_rows, chain):
        _add(synth, "txlist")

    # Persist
    result.new_tx = _insert_rows(buffer, wallet_id)

    for row in buffer:
        _upsert_token_review(wallet_id, chain, row["asset"], row.get("contract_address"))

    # Save incremental state — but ONLY for endpoints that completed without error.
    for endpoint, max_block in result.max_block_per_endpoint.items():
        if endpoint in result.endpoint_errors:
            continue
        if max_block > last_blocks.get(endpoint, 0):
            _save_last_block(wallet_id, chain, endpoint, max_block)

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
                for endpoint, err in result.endpoint_errors.items():
                    summary.errors.append(
                        f"{label} / {wallet['name']} / {endpoint}: {err}"
                    )
            except Exception as e:
                summary.errors.append(f"{label} / {wallet['name']}: {e}")

            time.sleep(0.15)

    if progress_fn:
        progress_fn(1.0, "Klaar")

    return summary
