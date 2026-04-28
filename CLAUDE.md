# CLAUDE.md — Crypto Portfolio Tracker

Lees dit bestand aan het begin van elke sessie. Alle instructies hier overschrijven standaard gedrag.

---

## 1. Doel en scope

Lokale crypto portfolio tracker (macOS). Python 3.12 + Streamlit + SQLite + httpx + uv.
Geen cloud, geen auth, geen private keys.

**Fase 1 (MVP) — dit is de actieve fase:**
- On-chain import via Etherscan V2 (ETH/ARB/BASE/OP/POL) + Routescan (BEAM)
- Wallet management
- Opt-in token review (scam filter, standaard alles UIT)
- Balansen per token per wallet

**Expliciet NIET in fase 1:**
Bitcoin, EUR/CoinGecko, cost basis, belastingrapport, staking-classificatie, CSV-import (Delta/Etherscan).
Bouw dit niet tenzij er expliciet om gevraagd wordt.

---

## 2. Bestandsstructuur

```
crypto-tracker/
├── CLAUDE.md
├── project_spec.md
├── pyproject.toml
├── .env                    # nooit committen
├── .env.example
├── .gitignore
├── app.py
├── data/portfolio.db
├── backups/
├── pages/
│   ├── 01_wallets.py
│   ├── 02_fetch.py
│   └── 03_balances.py
└── core/
    ├── db.py
    ├── models.py
    ├── api.py
    ├── fetcher.py
    └── backup.py
```

**Maximaal 400 regels per bestand.** Bij 350+ regels: splitsen voor je meer toevoegt.

**Strikte scheiding:**
- `core/api.py` raakt nooit de DB — puur HTTP
- `core/fetcher.py` roept api.py en db.py aan, bevat geen HTTP-code
- Pages bevatten geen business logic — ze roepen core-functies aan en renderen resultaten

---

## 3. Kritieke lessen (niet onderhandelen)

### Les 1 — Dedup key = (tx_hash, wallet_id), NOOIT alleen tx_hash

Dezelfde on-chain transactie verschijnt in de API-resultaten van meerdere wallets.
Als wallet A 100 USDC stuurt naar wallet B:
- A's tokentx: from=A, to=B, tx_hash=H → outflow (-100)
- B's tokentx: from=A, to=B, tx_hash=H → inflow (+100)

Dedup op alleen tx_hash → B's inflow wordt overgeslagen → negatief saldo.
**Oplossing:** `UNIQUE (tx_hash, wallet_id)` constraint in het schema. In geheugen: `set[tuple[str, int]]`.

### Les 2 — Altijd drie endpoints per wallet+chain

1. `tokentx` — ERC-20 transfers
2. `txlist` — native token direct sends + gas fees
3. `txlistinternal` — native via smart contracts (DEX swap-returns, unstake)

Zonder `txlistinternal`: ETH terug van een DEX-swap wordt niet geregistreerd → negatief ETH saldo.

### Les 3 — Gas fees zijn echte outflows

Gas fees altijd opslaan als aparte `GAS_FEE` rij, ook bij mislukte transacties.
De EVM chargeert gas ongeacht het transactieresultaat. Niet filteren.
Formule: `gasUsed * gasPrice / 10^18`

---

## 4. Chain configuratie

`CHAINS` in `core/models.py` is de enige bron van waarheid.

```python
CHAINS = {
    "ethereum": {"chainid": 1,     "native": "ETH",  "label": "Ethereum"},
    "arbitrum": {"chainid": 42161, "native": "ETH",  "label": "Arbitrum"},
    "base":     {"chainid": 8453,  "native": "ETH",  "label": "Base"},
    "optimism": {"chainid": 10,    "native": "ETH",  "label": "Optimism"},
    "polygon":  {"chainid": 137,   "native": "POL",  "label": "Polygon"},
    "beam":     {"chainid": 4337,  "native": "BEAM", "label": "BEAM"},
}
ROUTESCAN_CHAINS = {"beam"}
```

- Etherscan V2: `https://api.etherscan.io/v2/api?chainid={N}&apikey={KEY}&...`
- Routescan (BEAM): `https://api.routescan.io/v2/network/mainnet/evm/4337/etherscan/api?apikey={KEY}&...` (geen chainid param in body)

---

## 5. API-specifics

**Paginatie:** page_size=10.000, `startblock`/`endblock`, 0.25s sleep tussen pages, stop als len(result) < page_size.

**Amount conversie:**
- tokentx: `Decimal(raw["value"]) / 10 ** int(raw.get("tokenDecimal", "18") or "18")`
- txlist (value): `Decimal(raw["value"]) / 10**18`
- txlist (gas): `Decimal(raw["gasUsed"]) * Decimal(raw["gasPrice"]) / 10**18`
- txlistinternal: `Decimal(raw["value"]) / 10**18`

**Richting:**
- `TRANSFER_IN`: `to_addr == wallet_addr`
- `TRANSFER_OUT`: `from_addr == wallet_addr`
- `GAS_FEE`: `from_addr == wallet_addr` (altijd negatief)

**Mislukte transacties (`isError=1`):** skip value movement, maar GAS_FEE nog steeds opslaan.
**Zero-value internal calls:** overslaan.

**Synthetic hash voor internal txs:** `f"{outer_hash}_int_{global_idx}"` — voorkomt botsing met txlist-rij.

---

## 6. Database

Volledig schema in `core/db.py`. Geen migraties — schone start, versie 1.
Alle Decimal-bedragen als TEXT opslaan, nooit als float.
UUID als transactie-PK (niet AUTOINCREMENT).

---

## 7. Getallen en opmaak

- Alle bedragen: `from decimal import Decimal` — nooit float voor geld
- DB writes: `str(decimal_value)`
- DB reads: `Decimal(row["amount"])`
- Display: Nederlandse opmaak (komma als decimaalteken, punt als duizendtallen)

---

## 8. Git-regels

- `main` is altijd stabiel — nooit direct committen
- Branches: `feature/korte-naam`
- Nooit committen: `.env`, `*.db`, `backups/`
- Commit format: `[fase] korte omschrijving`

---

## 9. Commando's

```bash
# Start app
uv run streamlit run app.py

# DB resetten
uv run python -c "from core.db import reset_db; reset_db()"

# Dependency toevoegen
uv add package-naam
```
