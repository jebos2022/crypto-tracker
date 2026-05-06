"""
HTTP layer — paginated Etherscan V2 / Routescan API calls.
No DB access, no parsing, no UUIDs. Returns raw API dicts.

Pagination strategy
-------------------
Etherscan caps any single query at 10.000 records — incrementing `page`
beyond that returns nothing. We work in *block windows* instead: keep
`offset=10_000`, advance `startblock` past the highest block we just saw,
and repeat until a partial batch comes back. This handles wallets with
arbitrarily many transfers correctly.

Status handling
---------------
Etherscan signals different conditions all with `status="0"`:
  * "No transactions found"           — finished, return what we have
  * "NOTOK" + "Max rate limit reached" — sleep and retry
  * "NOTOK" + something else           — real error, raise EtherscanError

The previous version treated every `status != "1"` as "done" and silently
truncated the result on rate limits, leaving `last_block` advanced as if
the data were complete. That's the bug class this module exists to fix.
"""

import os
import time

import httpx

from core.api_public_evidence import (
    fetch_coingecko_token_data,
    fetch_coingecko_token_list,
    fetch_coinmarketcap_token_info,
    fetch_goplus_token_security,
)
from core.env import load_env
from core.models import CHAINS, ROUTESCAN_CHAINS, ETHERSCAN_BASE, ROUTESCAN_BASE, PAGE_SIZE


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class EtherscanError(Exception):
    """Raised on a real API error (bad params, server fault, exhausted retries)."""


class EtherscanRateLimit(EtherscanError):
    """Raised after MAX_RETRIES rate-limit responses on the same call."""


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

MAX_RETRIES = 5            # rate-limit retries per request
INITIAL_BACKOFF = 1.0      # seconds; doubles per retry (1, 2, 4, 8, 16)
INTER_PAGE_DELAY = 0.25    # seconds between successful pages, throttle to <5 req/s
DEFAULT_TIMEOUT = 30.0


# ---------------------------------------------------------------------------
# URL / param helpers
# ---------------------------------------------------------------------------

def _ensure_env_loaded() -> None:
    load_env()


def _api_url(chain: str) -> str:
    if chain in ROUTESCAN_CHAINS:
        chain_id = CHAINS[chain]["chainid"]
        return ROUTESCAN_BASE.format(chainid=chain_id)
    return ETHERSCAN_BASE


def _api_params(chain: str) -> dict:
    """Base params injected into every request (API key + optional chainid)."""
    _ensure_env_loaded()
    if chain in ROUTESCAN_CHAINS:
        key = os.getenv("ROUTESCAN_API_KEY", "")
        return {"apikey": key} if key else {}
    key = os.getenv("ETHERSCAN_API_KEY", "")
    if not key:
        raise ValueError("ETHERSCAN_API_KEY not set in .env")
    return {"chainid": CHAINS[chain]["chainid"], "apikey": key}


# ---------------------------------------------------------------------------
# Response classification
# ---------------------------------------------------------------------------

def _is_rate_limit(message: str, result) -> bool:
    """Heuristic: Etherscan's rate-limit responses are inconsistent."""
    haystack = f"{message} {result}".lower()
    return any(s in haystack for s in (
        "rate limit",
        "max calls per sec",
        "too many",
    ))


def _classify(data: dict) -> tuple[str, list]:
    """
    Inspect a parsed JSON response.

    Returns ("ok", batch)              — success, `batch` is a list (possibly empty)
    Returns ("empty", [])               — "No transactions found", finished
    Raises EtherscanRateLimit           — caller should sleep and retry
    Raises EtherscanError               — non-recoverable
    """
    status  = data.get("status")
    message = data.get("message", "")
    result  = data.get("result")

    if status == "1":
        return "ok", result if isinstance(result, list) else []

    # status == "0"
    if isinstance(result, list):
        # "No transactions found" — finished, no more pages.
        return "empty", []

    # result is a string error message at this point
    if _is_rate_limit(message, result):
        raise EtherscanRateLimit(f"{message}: {result}")

    raise EtherscanError(f"{message}: {result}")


# ---------------------------------------------------------------------------
# Paginated fetch
# ---------------------------------------------------------------------------

def _retry_loop(request_fn, classify_fn):
    backoff = INITIAL_BACKOFF
    for attempt in range(MAX_RETRIES):
        resp = request_fn()
        resp.raise_for_status()
        data = resp.json()
        try:
            return classify_fn(data)
        except EtherscanRateLimit:
            if attempt == MAX_RETRIES - 1:
                raise
            time.sleep(backoff)
            backoff *= 2
    raise EtherscanRateLimit("exhausted retries")


def _request_with_retry(client: httpx.Client, url: str, params: dict) -> tuple[str, list]:
    """One HTTP request, with rate-limit retries. Returns (status, batch)."""
    return _retry_loop(lambda: client.get(url, params=params), _classify)


def _paginate(
    url: str,
    base_params: dict,
    action_params: dict,
    *,
    startblock: int = 0,
    endblock: int = 99_999_999,
) -> list[dict]:
    """
    Fetch all rows for `action_params` between `startblock` and `endblock`,
    advancing the window past Etherscan's 10k-record query cap.
    """
    results: list[dict] = []
    cur_start = startblock

    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        while True:
            params = {
                **base_params,
                **action_params,
                "startblock": cur_start,
                "endblock":   endblock,
                "page":       1,
                "offset":     PAGE_SIZE,
                "sort":       "asc",
            }
            kind, batch = _request_with_retry(client, url, params)

            if kind == "empty" or not batch:
                break

            results.extend(batch)

            # Partial batch → reached the end of available data.
            if len(batch) < PAGE_SIZE:
                break

            # Full batch → likely more data past the 10k window cap.
            # Advance startblock past the highest block we just saw.
            try:
                last_block = max(int(r.get("blockNumber", "0") or "0") for r in batch)
            except ValueError:
                # Unexpected non-integer blockNumber; bail to avoid infinite loop.
                break

            next_start = last_block + 1
            if next_start <= cur_start:
                # Defensive: would loop forever (>=10k records in a single block,
                # virtually impossible for one wallet but cheap to guard against).
                break
            cur_start = next_start

            time.sleep(INTER_PAGE_DELAY)

    return results


# ---------------------------------------------------------------------------
# Endpoint wrappers
# ---------------------------------------------------------------------------

def fetch_tokentx(address: str, chain: str, startblock: int = 0) -> list[dict]:
    """ERC-20 token transfers for a wallet address."""
    return _paginate(
        _api_url(chain),
        _api_params(chain),
        {
            "module":  "account",
            "action":  "tokentx",
            "address": address.lower(),
        },
        startblock=startblock,
    )


def fetch_txlist(address: str, chain: str, startblock: int = 0) -> list[dict]:
    """Native token direct transactions (includes gas data)."""
    return _paginate(
        _api_url(chain),
        _api_params(chain),
        {
            "module":  "account",
            "action":  "txlist",
            "address": address.lower(),
        },
        startblock=startblock,
    )


def fetch_tokeninfo(contract_address: str, chain: str) -> dict | None:
    """Token metadata: verification, holder count, social presence. Etherscan V2 only."""
    if chain in ROUTESCAN_CHAINS:
        return None
    url = _api_url(chain)
    base = _api_params(chain)
    with httpx.Client(timeout=30) as client:
        resp = client.get(url, params={
            **base,
            "module": "token",
            "action": "tokeninfo",
            "contractaddress": contract_address.lower(),
        })
        resp.raise_for_status()
        data = resp.json()
    if data.get("status") != "1":
        return None
    result = data.get("result") or []
    return result[0] if isinstance(result, list) else result


def fetch_txlistinternal(address: str, chain: str, startblock: int = 0) -> list[dict]:
    """Native token movements via smart contracts (DEX returns, unstaking)."""
    return _paginate(
        _api_url(chain),
        _api_params(chain),
        {
            "module":  "account",
            "action":  "txlistinternal",
            "address": address.lower(),
        },
        startblock=startblock,
    )


# ---------------------------------------------------------------------------
# Live balance lookups (single-call, no pagination)
# ---------------------------------------------------------------------------

def _classify_single_result(data: dict) -> str:
    status = data.get("status")
    message = data.get("message", "")
    result = data.get("result")
    if status == "1":
        return str(result)
    if _is_rate_limit(message, result):
        raise EtherscanRateLimit(f"{message}: {result}")
    raise EtherscanError(f"{message}: {result}")


def _single_call(url: str, params: dict) -> str:
    """
    Issue a single balance/tokenbalance request and return the raw `result`
    string (an unscaled integer). Reuses the rate-limit retry logic from
    `_request_with_retry` but bypasses the pagination loop — these endpoints
    return one number, not a list.
    """
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        return _retry_loop(lambda: client.get(url, params=params), _classify_single_result)


def _parse_int_result(raw: str, label: str) -> int:
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise EtherscanError(f"non-numeric {label} result: {raw!r}") from exc


def fetch_native_balance(address: str, chain: str) -> int:
    """
    Live native-token balance (ETH/POL/BEAM) in wei. Use `decimals=18`
    universally to scale.
    """
    url = _api_url(chain)
    params = {
        **_api_params(chain),
        "module":  "account",
        "action":  "balance",
        "address": address.lower(),
        "tag":     "latest",
    }
    return _parse_int_result(_single_call(url, params), "balance")


def fetch_token_balance(address: str, contract_address: str, chain: str) -> int:
    """
    Live ERC-20 balance (raw, unscaled integer). Caller must scale by the
    token's decimals to get a human-readable amount.
    """
    url = _api_url(chain)
    params = {
        **_api_params(chain),
        "module":          "account",
        "action":          "tokenbalance",
        "contractaddress": contract_address.lower(),
        "address":         address.lower(),
        "tag":             "latest",
    }
    return _parse_int_result(_single_call(url, params), "tokenbalance")


def fetch_token_supply(contract_address: str, chain: str) -> int:
    """Total circulating supply of a token (raw, unscaled integer)."""
    url = _api_url(chain)
    params = {
        **_api_params(chain),
        "module":          "stats",
        "action":          "tokensupply",
        "contractaddress": contract_address.lower(),
    }
    return _parse_int_result(_single_call(url, params), "tokensupply")
