"""
HTTP helpers for token-review public evidence sources.

These functions are intentionally DB-free and return raw API payloads. They are
kept separate from the Etherscan/Routescan transaction API layer so new public
evidence providers do not enlarge core/api.py.
"""

import os

import httpx

from core.env import load_env

DEFAULT_TIMEOUT = 30.0
COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COINGECKO_TOKEN_LIST_BASE = "https://tokens.coingecko.com"
GOPLUS_BASE = "https://api.gopluslabs.io/api/v1"
COINMARKETCAP_BASE = "https://pro-api.coinmarketcap.com/v2"


def _ensure_env_loaded() -> None:
    load_env()


def _coingecko_headers() -> dict:
    _ensure_env_loaded()
    key = os.getenv("COINGECKO_API_KEY", "").strip()
    return {"x-cg-demo-api-key": key} if key else {}


def _coinmarketcap_headers() -> dict:
    _ensure_env_loaded()
    key = os.getenv("COINMARKETCAP_API_KEY", "").strip()
    return {"X-CMC_PRO_API_KEY": key} if key else {}


def fetch_coingecko_token_list(asset_platform_id: str) -> dict | None:
    """CoinGecko token list for one asset platform."""
    url = f"{COINGECKO_TOKEN_LIST_BASE}/{asset_platform_id}/all.json"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()


def fetch_coingecko_token_data(network: str, contract_address: str) -> dict | None:
    """CoinGecko on-chain token data by exact contract address."""
    headers = _coingecko_headers()
    if not headers:
        return None
    url = f"{COINGECKO_BASE}/coins/{network}/contract/{contract_address.lower()}"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(url, headers=headers)
        if resp.status_code in (401, 403, 404):
            return None
        resp.raise_for_status()
        return resp.json()


def fetch_goplus_token_security(chain_id: int, contract_address: str) -> dict | None:
    """GoPlus token security/risk data by exact contract address."""
    _ensure_env_loaded()
    url = f"{GOPLUS_BASE}/token_security/{chain_id}"
    headers = {}
    token = os.getenv("GOPLUS_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(
            url,
            params={"contract_addresses": contract_address.lower()},
            headers=headers,
        )
        if resp.status_code in (401, 403, 404):
            return None
        resp.raise_for_status()
        data = resp.json()
    result = data.get("result") or {}
    if not isinstance(result, dict):
        return None
    return result.get(contract_address.lower()) or result.get(contract_address)


def fetch_coinmarketcap_token_info(contract_address: str) -> dict | None:
    """CoinMarketCap token metadata by exact contract address."""
    headers = _coinmarketcap_headers()
    if not headers:
        return None
    with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
        resp = client.get(
            f"{COINMARKETCAP_BASE}/cryptocurrency/info",
            params={"address": contract_address.lower()},
            headers=headers,
        )
        if resp.status_code in (401, 403, 404):
            return None
        resp.raise_for_status()
        data = resp.json()
    payload = data.get("data") or {}
    if isinstance(payload, dict) and payload:
        return payload
    return None
