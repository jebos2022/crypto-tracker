import pandas as pd

from core.ledger import explorer_address_url, explorer_tx_url, normalize_tx_hash
from core.token_review import get_recent_token_transactions, token_intake_guidance
from core.token_valuation import VALUATION_ACTIVE


def contract_label(contract: str | None) -> str:
    if not contract:
        return "native"
    return f"{contract[:10]}…{contract[-6:]}"


def valuation_label(status: str | None, valuation_status_to_label: dict[str, str]) -> str:
    return valuation_status_to_label.get(status or VALUATION_ACTIVE, "Marktprijs")


def token_df(tokens: list[dict], valuation_status_to_label: dict[str, str]) -> pd.DataFrame:
    rows = []
    for token in tokens:
        guidance = token_intake_guidance(token)
        rows.append({
            "Advies": guidance.action,
            "Waarom": guidance.why,
            "Status": _status_label(token["review_status"]),
            "Chain": token["chain"],
            "Token": token["asset"],
            "Contract": contract_label(token.get("contract_address")),
            "Explorer": explorer_address_url(token["chain"], token.get("contract_address")),
            "Signaal": token.get("review_reason") or "",
            "Patroon": _unknown_hint(token),
            "Netto": _net_label(token),
            "Tx": int(token.get("tx_count") or 0),
            "In": int(token.get("in_count") or 0),
            "Uit": int(token.get("out_count") or 0),
            "Eerst": (token.get("first_seen") or "")[:10],
            "Laatst": (token.get("last_seen") or "")[:10],
            "Houders": token["holder_count"] if token.get("holder_count") is not None else "—",
            "Wallets": token["wallet_count"],
            "Bron": "handmatig" if token.get("decision_source") == "user" else "auto",
            "Waardering": valuation_label(token.get("valuation_status"), valuation_status_to_label),
            "Vanaf": token.get("valuation_effective_date") or "",
            "Notitie": token.get("valuation_reason") or "",
            "Importeren": bool(token["accepted"]),
        })
    return pd.DataFrame(rows)


def tx_context_df(token: dict) -> pd.DataFrame:
    rows = []
    for row in get_recent_token_transactions(token["chain"], token["token_key"], limit=5):
        rows.append({
            "Datum": row["timestamp"].replace("T", " ")[:19],
            "Wallet": row["wallet"],
            "Bedrag": row["amount"],
            "Asset": row["asset"],
            "Contract": contract_label(row.get("contract_address")),
            "Tx": normalize_tx_hash(row["tx_hash"])[:12] + "…",
            "Bron": row["source"],
            "Actie": row.get("method_name") or "",
            "Explorer": explorer_tx_url(token["chain"], row["tx_hash"]),
        })
    return pd.DataFrame(rows)


def context_button_key(prefix: str, token: dict) -> str:
    raw = f"{prefix}_{token['chain']}_{token['token_key']}"
    return "".join(ch if ch.isalnum() else "_" for ch in raw)


def _status_label(status: str) -> str:
    return {
        "safe": "Zeker goed",
        "unknown": "Onbekend",
        "suspicious": "Verdacht",
        "scam": "Scam",
    }.get(status, status)


def _unknown_hint(token: dict) -> str:
    in_count = int(token.get("in_count") or 0)
    out_count = int(token.get("out_count") or 0)
    tx_count = int(token.get("tx_count") or 0)
    self_swap_count = int(token.get("self_initiated_swap_count") or 0)
    bulk_airdrop_count = int(token.get("bulk_airdrop_count") or 0)
    if token["review_status"] == "safe":
        return ""
    if tx_count == 0:
        return "Geen transacties"
    if self_swap_count > 0:
        return "Eigen DEX-swap"
    if bulk_airdrop_count > 0:
        return "Bulk-airdrop"
    if in_count > 0 and out_count == 0:
        return "Alleen inkomend"
    if out_count > 0:
        return "Eigen activiteit"
    return "Onbekend patroon"


def _net_label(token: dict) -> str:
    value = token.get("net_amount")
    if value is None:
        return "-"
    try:
        return f"{float(value):,.8g}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "-"
