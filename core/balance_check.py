"""
Live balance verification — compares the wallet's reconstructed balance
(sum of all transfer rows in `transactions`) with the on-chain truth from
Etherscan's `balance` / `tokenbalance` endpoints.

A non-zero delta means our reconstruction is missing or misclassifying
something. Common causes (in order of frequency):
  * Rebasing tokens (stETH, AMPL, etc.) — balance changes without transfers
  * Fee-on-transfer tokens (RFI-style) — sender's `value` ≠ recipient's
  * Bridge-OUT to a chain we don't track (already flagged with 🌉)
  * Same-symbol collision (two contracts, one `asset` row)
  * Transactions outside our import scope (CEX off-ramps, ignored chains)

Each (wallet, chain, asset) requires one API call. With Etherscan free-tier
at 5 req/s, a portfolio of 100 tokens takes ~20 seconds. We don't cache
results to disk — verify on demand from the UI.
"""

from dataclasses import dataclass
from decimal import Decimal

from core import api
from core.db import get_connection
from core.models import CHAINS
from core.token_review import token_key_sql, token_review_join_condition


@dataclass
class BalanceCheckRow:
    wallet:           str
    chain:            str
    asset:            str
    contract_address: str | None  # None for native token
    computed:         Decimal     # what `transactions` sums to
    onchain:          Decimal | None  # None if lookup failed
    delta:            Decimal | None  # onchain - computed; None if lookup failed
    error:            str | None  # exception message if call failed
    decimals_known:   bool        # False = we couldn't scale (no token_meta row)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _accepted_balances(wallet_id: int | None) -> list[dict]:
    """
    Return current computed balances per (wallet, chain, asset) for accepted
    tokens. Includes the contract_address (or NULL for native) needed for
    on-chain lookup.

    Aggregates in Python to keep Decimal exact without issuing one query per
    accepted token.
    """
    conn = get_connection()
    try:
        sql = f"""
            SELECT
                w.name                         AS wallet,
                w.id                           AS wallet_id,
                w.address                      AS address,
                t.chain                        AS chain,
                t.asset                        AS asset,
                {token_key_sql("t")}           AS token_key,
                t.contract_address             AS contract_address,
                t.amount                       AS amount
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

        totals: dict[tuple, dict] = {}
        for r in rows:
            key = (r["wallet_id"], r["chain"], r["token_key"], r["asset"])
            entry = totals.setdefault(key, {
                "wallet":           r["wallet"],
                "address":          r["address"],
                "chain":            r["chain"],
                "asset":            r["asset"],
                "contract_address": (r["contract_address"] or "").lower() or None,
                "computed":         Decimal("0"),
            })
            entry["computed"] += Decimal(r["amount"])
        return list(totals.values())
    finally:
        conn.close()


def _get_decimals(chain: str, contract_address: str | None) -> int | None:
    """Native = 18 (all our chains). ERC-20 = look up token_meta."""
    if contract_address is None:
        return 18  # all our chains use 18-decimal native tokens (ETH, POL, BEAM)
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT decimals FROM token_meta WHERE chain=? AND contract_address=?",
            (chain, contract_address.lower()),
        ).fetchone()
        return row["decimals"] if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def verify_balances(
    wallet_id: int | None = None,
    progress_fn=None,
) -> list[BalanceCheckRow]:
    """
    For every accepted (wallet, chain, asset), call the appropriate Etherscan
    endpoint and compare with the computed balance.

    progress_fn(fraction, label): optional callback for UI progress.
    """
    rows = _accepted_balances(wallet_id)
    output: list[BalanceCheckRow] = []
    total = max(len(rows), 1)

    for i, r in enumerate(rows):
        if progress_fn:
            progress_fn(i / total, f"{r['wallet']} / {r['chain']} / {r['asset']}")

        chain    = r["chain"]
        asset    = r["asset"]
        contract = r["contract_address"]
        is_native_symbol = asset == CHAINS.get(chain, {}).get("native")
        is_renamed_native = isinstance(contract, str) and asset.startswith(
            CHAINS.get(chain, {}).get("native", "") + "-"
        )
        # "Native row" = symbol matches the chain's native token AND no contract.
        # Wrapped natives (WETH) and renamed natives ("ETH-0x1234") are ERC-20.
        is_native = (contract is None) and is_native_symbol and not is_renamed_native

        decimals = _get_decimals(chain, None if is_native else contract)
        decimals_known = decimals is not None

        onchain: Decimal | None = None
        delta:   Decimal | None = None
        error:   str | None     = None

        try:
            if is_native:
                raw = api.fetch_native_balance(r["address"], chain)
                onchain = Decimal(raw) / Decimal("10") ** 18
            elif contract:
                raw = api.fetch_token_balance(r["address"], contract, chain)
                if decimals_known:
                    onchain = Decimal(raw) / Decimal("10") ** decimals
                else:
                    # Can't scale — report raw integer; UI shows a hint.
                    onchain = Decimal(raw)
            else:
                # Edge case: ERC-20 row with no contract_address (shouldn't
                # happen post-fetch, but guard anyway).
                error = "missing contract_address — re-fetch this wallet"
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

        if onchain is not None and decimals_known:
            delta = onchain - r["computed"]

        output.append(BalanceCheckRow(
            wallet           = r["wallet"],
            chain            = chain,
            asset            = asset,
            contract_address = contract,
            computed         = r["computed"],
            onchain          = onchain,
            delta            = delta,
            error            = error,
            decimals_known   = decimals_known,
        ))

    if progress_fn:
        progress_fn(1.0, "Klaar")

    return output
