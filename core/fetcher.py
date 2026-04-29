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
from core.models import (
    CHAINS, WETH_CONTRACTS,
    TRANSFER_IN, TRANSFER_OUT, BRIDGE_IN, BRIDGE_OUT, GAS_FEE,
    is_bridge_contract,
    to_decimal, to_db,
)


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

    is_inflow = (to_addr == wallet)
    counterparty = from_addr if is_inflow else to_addr
    bridge_name = is_bridge_contract(chain, counterparty)

    if bridge_name:
        direction = BRIDGE_IN if is_inflow else BRIDGE_OUT
    else:
        direction = TRANSFER_IN if is_inflow else TRANSFER_OUT
    signed = abs(amount_raw) if is_inflow else -abs(amount_raw)

    symbol   = raw.get("tokenSymbol", "").strip()
    contract = raw.get("contractAddress", "").lower() or None

    # ERC-20 token whose symbol matches the chain's native token (e.g. an "ETH"
    # vault token on Arbitrum). Keep it separate from native ETH by tagging it
    # with the first 6 chars of its contract address.
    if contract and symbol == CHAINS[chain]["native"]:
        symbol = f"{symbol}-{contract[:6]}"

    return {
        "id":               str(uuid.uuid4()),
        "chain":            chain,
        "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
        "block_number":     int(raw.get("blockNumber", "0") or "0"),
        "tx_hash":          raw.get("hash", ""),
        "type":             direction,
        "asset":            symbol,
        "contract_address": contract,
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
            is_inflow = (to_addr == wallet)
            counterparty = from_addr if is_inflow else to_addr
            if is_bridge_contract(chain, counterparty):
                direction = BRIDGE_IN if is_inflow else BRIDGE_OUT
            else:
                direction = TRANSFER_IN if is_inflow else TRANSFER_OUT
            amount_eth = value_wei / Decimal("10") ** 18
            signed = abs(amount_eth) if is_inflow else -abs(amount_eth)
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
    is_inflow = (to_addr == wallet)
    counterparty = from_addr if is_inflow else to_addr
    if is_bridge_contract(chain, counterparty):
        direction = BRIDGE_IN if is_inflow else BRIDGE_OUT
    else:
        direction = TRANSFER_IN if is_inflow else TRANSFER_OUT
    amount = value_wei / Decimal("10") ** 18
    signed = abs(amount) if is_inflow else -abs(amount)
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
        if h and h in known:
            result.skipped += 1
            return
        bn = row.get("block_number", 0)
        prev = result.max_block_per_endpoint.get(endpoint, 0)
        if bn > prev:
            result.max_block_per_endpoint[endpoint] = bn
        buffer.append(row)
        if h:
            known.add(h)
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
        # Buffer token-meta upserts to avoid hammering the DB inside the loop.
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
                # Capture decimals + symbol for balance verification later.
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
    # Also collect raw txlist rows for WETH reconciliation in step 4.
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

    # 4 — Native-wrap reconciliation
    # Some contracts (WETH and similar) wrap native ETH into an ERC-20 with symbol
    # "ETH". Etherscan tokentx omits the Transfer(0x0, wallet, amount) mint event.
    # We detect missing mints by matching txlist deposits (to=contract, value>0)
    # against TRANSFER_INs in the buffer, and synthesise the missing rows.
    #
    # Covers two cases:
    #   a) Known WETH contracts from WETH_CONTRACTS (symbol "WETH")
    #   b) Any contract whose tokentx rows had their symbol renamed to "{native}-0x…"
    #      because it collided with the native token symbol

    native = CHAINS[chain]["native"]
    wrap_contracts: dict[str, str] = {}  # contract_addr → asset symbol

    weth_addr = WETH_CONTRACTS.get(chain)
    if weth_addr:
        wrap_contracts[weth_addr] = "WETH"

    for r in buffer:
        if r.get("source") == "tokentx" and r.get("contract_address"):
            sym = r["asset"]
            if sym.startswith(native + "-"):
                wrap_contracts[r["contract_address"]] = sym

    for contract_addr, sym in wrap_contracts.items():
        ins_seen = {
            r["tx_hash"] for r in buffer
            if r["asset"] == sym and r["type"] == TRANSFER_IN
        }
        for raw in txlist_rows:
            if raw.get("isError", "0") == "1":
                continue
            if raw.get("to", "").lower() != contract_addr:
                continue
            value_wei = to_decimal(raw.get("value", "0"))
            if value_wei <= 0:
                continue
            h = raw.get("hash", "")
            if h in ins_seen or any(k.startswith(h + "_dup") for k in ins_seen):
                continue
            amount = value_wei / Decimal("10") ** 18
            _add({
                "id":               str(uuid.uuid4()),
                "chain":            chain,
                "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
                "block_number":     int(raw.get("blockNumber", "0") or "0"),
                "tx_hash":          f"{h}_wrap_{contract_addr[:6]}",
                "type":             TRANSFER_IN,
                "asset":            sym,
                "contract_address": contract_addr,
                "amount":           to_db(amount),
                "source":           "txlist",
            }, "txlist")

    # 4b — Amount-based fallback for ETH-renamed tokens routed via a DEX/router.
    # When ETH is sent to a router (not directly to the vault), the to-address check
    # above doesn't fire. These vaults are 1:1 wrappers, so the ETH outflow amount
    # equals the token deficit exactly. If there's exactly one txlist ETH outflow
    # matching the deficit and no TRANSFER_IN exists yet, synthesise it.
    for contract_addr, sym in wrap_contracts.items():
        if sym == "WETH":
            continue
        buf_ins  = [r for r in buffer if r["asset"] == sym and r["type"] == TRANSFER_IN]
        buf_outs = [r for r in buffer if r["asset"] == sym and r["type"] == TRANSFER_OUT]
        if not buf_outs or buf_ins:
            continue
        deficit = sum(abs(Decimal(r["amount"])) for r in buf_outs)
        candidates = [
            raw for raw in txlist_rows
            if raw.get("isError", "0") != "1"
            and to_decimal(raw.get("value", "0")) / Decimal("10") ** 18 == deficit
        ]
        if len(candidates) != 1:
            continue
        raw = candidates[0]
        h = raw.get("hash", "")
        _add({
            "id":               str(uuid.uuid4()),
            "chain":            chain,
            "timestamp":        _unix_to_iso(raw.get("timeStamp", "0")),
            "block_number":     int(raw.get("blockNumber", "0") or "0"),
            "tx_hash":          f"{h}_wrap_amt_{contract_addr[:6]}",
            "type":             TRANSFER_IN,
            "asset":            sym,
            "contract_address": contract_addr,
            "amount":           to_db(deficit),
            "source":           "txlist",
        }, "txlist")

    # Persist
    result.new_tx = _insert_rows(buffer, wallet_id)

    # Update token_review for newly seen tokens
    for row in buffer:
        _upsert_token_review(wallet_id, chain, row["asset"], row.get("contract_address"))

    # Save incremental state — but ONLY for endpoints that completed without
    # error. A failed endpoint keeps its old cursor so the next fetch retries
    # the same range instead of silently skipping the missed window.
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
                # Surface per-endpoint failures (rate limit, server errors)
                # so the UI can show them without scaring the user — the
                # data is still partially fetched, just not the full window.
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

