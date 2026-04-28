"""
HTTP layer — paginated Etherscan V2 / Routescan API calls.
No DB access, no parsing, no UUIDs. Returns raw API dicts.
"""

import os
import time

import httpx

from core.models import CHAINS, ROUTESCAN_CHAINS, ETHERSCAN_BASE, ROUTESCAN_BASE, PAGE_SIZE


def _api_url(chain: str) -> str:
    if chain in ROUTESCAN_CHAINS:
        chain_id = CHAINS[chain]["chainid"]
        return ROUTESCAN_BASE.format(chainid=chain_id)
    return ETHERSCAN_BASE


def _api_params(chain: str) -> dict:
    """Base params injected into every request (API key + optional chainid)."""
    if chain in ROUTESCAN_CHAINS:
        key = os.getenv("ROUTESCAN_API_KEY", "")
        return {"apikey": key} if key else {}
    key = os.getenv("ETHERSCAN_API_KEY", "")
    if not key:
        raise ValueError("ETHERSCAN_API_KEY not set in .env")
    return {"chainid": CHAINS[chain]["chainid"], "apikey": key}


def _paginate(url: str, base_params: dict, action_params: dict) -> list[dict]:
    """Fetch all pages for a given action. Returns combined result list."""
    results: list[dict] = []
    page = 1
    with httpx.Client(timeout=30) as client:
        while True:
            params = {
                **base_params,
                **action_params,
                "page": page,
                "offset": PAGE_SIZE,
                "sort": "asc",
            }
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") != "1":
                break
            batch = data["result"]
            results.extend(batch)
            if len(batch) < PAGE_SIZE:
                break
            page += 1
            time.sleep(0.25)
    return results


def fetch_tokentx(address: str, chain: str, startblock: int = 0) -> list[dict]:
    """ERC-20 token transfers for a wallet address."""
    url = _api_url(chain)
    base = _api_params(chain)
    return _paginate(url, base, {
        "module": "account",
        "action": "tokentx",
        "address": address.lower(),
        "startblock": startblock,
        "endblock": 99_999_999,
    })


def fetch_txlist(address: str, chain: str, startblock: int = 0) -> list[dict]:
    """Native token direct transactions (includes gas data)."""
    url = _api_url(chain)
    base = _api_params(chain)
    return _paginate(url, base, {
        "module": "account",
        "action": "txlist",
        "address": address.lower(),
        "startblock": startblock,
        "endblock": 99_999_999,
    })


def fetch_txlistinternal(address: str, chain: str, startblock: int = 0) -> list[dict]:
    """Native token movements via smart contracts (DEX returns, unstaking)."""
    url = _api_url(chain)
    base = _api_params(chain)
    return _paginate(url, base, {
        "module": "account",
        "action": "txlistinternal",
        "address": address.lower(),
        "startblock": startblock,
        "endblock": 99_999_999,
    })
