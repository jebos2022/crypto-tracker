# CLAUDE.md — Crypto Portfolio Tracker

Lees dit bestand aan het begin van elke sessie. Alle instructies hier overschrijven standaard gedrag.
Volledige fase-/blok-indeling in [project_spec.md](project_spec.md). Review-instructies in [REVIEW.md](REVIEW.md).

---

## 1. Doel en scope

Lokale crypto portfolio tracker (macOS). Python 3.12 + Streamlit + SQLite + httpx + uv.
Geen cloud, geen auth, geen private keys.

Het project is opgedeeld in 8 fasen, elk uit blokken (zie [project_spec.md](project_spec.md)).
De huidige actieve fase staat bovenaan in project_spec.md. Bouw nooit vooruit op een latere
fase tenzij expliciet gevraagd.

---

## 2. Bestandsstructuur

```
crypto-tracker/
├── CLAUDE.md
├── REVIEW.md
├── project_spec.md
├── CHECKLIST.md
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
    ├── parsers.py
    ├── fetcher.py
    ├── token_review.py
    ├── balance_check.py
    ├── staking.py
    └── backup.py
```

**Maximaal 400 regels per bestand.** Bij 350+ regels: splitsen voor je meer toevoegt.

**Strikte scheiding:**
- `core/api.py` raakt nooit de DB — puur HTTP
- `core/parsers.py` is pure data-transformatie (raw API-row → dict), geen DB, geen HTTP
- `core/fetcher.py` orkestreert: roept `api` + `parsers` + `db` aan, bevat geen HTTP-code
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
- Branches per blok: `feature/x-y-naam` (zie blok in project_spec.md)
- Nooit committen: `.env`, `*.db`, `backups/`
- Commit format: `[fase x.y] korte omschrijving`

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

---

## 10. Werkwijze per blok

Een blok is de kleinste mergebare eenheid. Volg deze flow:

```
1. Branch:  git checkout -b feature/x-y-naam
2. Bouwen:  per acceptatiecriterium één commit
3. Testen:  alle test-scenarios uit project_spec.md handmatig doorlopen
4. Review:  /review (lokaal, Sonnet) — fix bevindingen
5. Merge:   PR maken, mergen naar main, branch verwijderen
```

Aan het eind van elke fase: `/ultrareview` (Opus, grondig) op alle blokken samen.

---

## 11. Kickoff per nieuwe fase (Opus)

Aan het begin van een fase doorloop dit protocol vóór er code geschreven wordt:

1. **Scope-analyse** — relevante code, doel van de fase en gerelateerde memory lezen
2. **Vragenlijst** — open vragen stellen tot 95% helder is
3. **Blok-uitwerking** — per blok: doel, files, acceptatiecriteria, test-scenarios, model
4. **Risico's & afhankelijkheden** — wat moet eerder klaar? Welk schema verandert?
5. **Akkoord** — gebruiker bevestigt blok-indeling vóór er gebouwd wordt

---

## 12. Model-tiering

Modelkeuze is sessie-niveau (`/model`). Per blok staat in project_spec.md welk
model aanbevolen is.

| Model | Wanneer |
|---|---|
| **Opus 4.7** | Architectuur, schemawijzigingen, complexe algoritmes, fase-kickoff, security review |
| **Sonnet 4.6** | Standaard implementatie binnen bekend patroon, UI-pagina's, code review per blok, refactors |
| **Haiku 4.5** | Mechanische taken volgens een al uitgewerkt plan: file moves, simpele tests, doc-updates |

---

## 13. Review-flow

We werken op een individueel plan zonder betaalde managed reviews. De flow:

- **Per blok**: `/review` skill of `code-review` plugin lokaal — Sonnet, snel
- **Per fase**: `/ultrareview` op alle blokken samen — Opus, grondig
- **Instructies**: zowel `/review` als `/ultrareview` lezen [REVIEW.md](REVIEW.md) als
  hoogste-prioriteit gids voor wat Important vs Nit is in dit project

REVIEW.md bevat de project-specifieke severity-calibratie (Decimal-correctheid =
Important, Streamlit-styling = Nit max). Pas REVIEW.md aan zodra een nieuwe
foutklasse blijkt belangrijk te zijn.
