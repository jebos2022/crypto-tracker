# Checklist — Crypto Tracker

Spiegelt [project_spec.md](project_spec.md). Eén checkbox per blok-acceptatiecriterium.
Afvinken = gedaan + getest + gemerged naar main.

Volgorde van werken: kickoff (Opus) per fase → blokken sequentieel → fase-review (`/ultrareview`).

---

## Setup

- [x] Nieuwe map aangemaakt (`crypto-tracker/`)
- [x] Git repo geïnitialiseerd
- [x] uv project + dependencies (streamlit, httpx, python-dotenv)
- [x] CLAUDE.md + project_spec.md + REVIEW.md geschreven
- [x] GitHub repo aangemaakt en gekoppeld
- [x] `.env` aanmaken met API keys (`cp .env.example .env`)

---

## Fase 1 — On-chain MVP afronden

### Eerder gebouwd (al klaar)

- [x] `core/db.py` — schema (wallets, transactions, token_review, wallet_chain_state, token_metadata)
- [x] `core/models.py` — CHAINS, BRIDGE_CONTRACTS, STAKED_TOKENS, Decimal helpers
- [x] `core/api.py` — HTTP-laag (tokentx, txlist, txlistinternal, tokeninfo, balances, supply)
- [x] `core/parsers.py` — row parsers (geëxtraheerd uit fetcher)
- [x] `core/fetcher.py` — fetch pipeline, dedup op (tx_hash, wallet_id)
- [x] `core/token_review.py` — scam regex + metadata + tokeninfo enrichment + sync_staking_wrappers
- [x] `core/staking.py` — get_staking_rate, all_staking_rates
- [x] `core/balance_check.py` — on-chain verificatie van computed balansen
- [x] `core/backup.py` — automatische backups
- [x] `pages/01_wallets.py` — wallet management
- [x] `pages/02_fetch.py` — fetch + token review + metadata enrichment
- [x] `pages/03_balances.py` — balansen + bridge expander + on-chain verificatie

### Blok 1.A — fetcher.py refactor + main.py opruimen
**Branch:** feature/1-a-fetcher-refactor — **Model:** Sonnet
- [ ] core/fetcher.py < 400 regels
- [ ] Wrap-reconciliation logica geëxtraheerd naar eigen module
- [ ] main.py weg of vervangen door zinvolle entrypoint
- [ ] Bestaande publieke API ongewijzigd
- [ ] Test: happy path / wrap-edge / regressie incremental
- [ ] /review groen → merge

### Blok 1.B — ETH 96 dataverlies herstellen
**Branch:** geen — operationele actie — **Model:** Sonnet
- [ ] wallet_chain_state reset (main + ethereum + txlist)
- [ ] Re-fetch uitgevoerd
- [ ] On-chain verificatie ETH/main toont ✅
- [ ] Test: geen dubbele transacties / andere wallets onaangetast

### Blok 1.C — PEAR/Arbitrum fetch debuggen
**Branch:** feature/1-c-pear-debug — **Model:** Opus
- [ ] Root cause schriftelijk vastgelegd
- [ ] PEAR + stPEAR zichtbaar in token-review na fetch
- [ ] stPEAR auto-accepted zodra PEAR accepted
- [ ] Test: happy path / leeg / regressie andere chains
- [ ] /review groen → merge

### Blok 1.D — BEAM node staking saldo tonen
**Branch:** feature/1-d-beam-staking — **Model:** Opus
- [ ] BEAM-staking-positie zichtbaar op balansen-pagina
- [ ] Reproduceerbare berekening, formule in code gedocumenteerd
- [ ] Werkt zonder volledige re-fetch
- [ ] Test: 5M zichtbaar / lege wallet / regressie andere balansen
- [ ] /review groen → merge

### Blok 1.E — Memory + spec opschonen
**Branch:** feature/1-e-memory-cleanup — **Model:** Haiku
- [ ] WIP staked-tokens memory weg
- [ ] project_open_issues.md gemarkeerd "afgehandeld"
- [ ] CHECKLIST in lijn met spec
- [ ] Test: geen verwijzingen naar oude memory / project_later_list intact

### Fase 1 afgerond
- [ ] `/ultrareview` op fase 1 (alle blokken samen)
- [ ] Alle 3 open issues gesloten

---

## Fase 2 — Ledger-pagina (transactiehistorie)

### Kickoff (Opus)
- [ ] Scope-analyse + vragenlijst
- [ ] Blok-uitwerking bevestigd

### Blok 2.A — Pagina "Transacties"
**Branch:** feature/2-a-ledger-page — **Model:** Sonnet
- [ ] Filter wallet (incl. "alle"), chain, token
- [ ] Sorteer op datum (default desc)
- [ ] Kolommen: datum, type, bedrag, asset, tx_hash (kort), bron-endpoint
- [ ] Etherscan-link per rij
- [ ] Test: happy / leeg / regressie
- [ ] /review groen → merge

### Blok 2.B — Export naar CSV
**Branch:** feature/2-b-ledger-export — **Model:** Haiku
- [ ] Download-knop levert CSV met huidige filter
- [ ] Bestandsnaam bevat wallet/token/datum
- [ ] Test: happy / lege filter / regressie
- [ ] /review groen → merge

### Fase 2 afgerond
- [ ] `/ultrareview` op fase 2

---

## Fase 3 — EUR-prijslaag (CoinGecko)

### Kickoff (Opus)
- [ ] Scope-analyse + vragenlijst
- [ ] Blok-uitwerking bevestigd

### Blok 3.A — price_cache schema + CoinGecko HTTP-laag
**Branch:** feature/3-a-prices-core — **Model:** Opus
- [ ] Tabel price_cache UNIQUE(asset, date)
- [ ] core/coingecko.py met fetch_price
- [ ] Rate-limit afgevangen
- [ ] Mapping asset_symbol → coingecko_id
- [ ] Test: happy / onbekend symbool / rate limit retry
- [ ] /review groen → merge

### Blok 3.B — Spotprijs op transactiemoment
**Branch:** feature/3-b-spot-pricing — **Model:** Sonnet
- [ ] eur_value(asset, date, amount) helper
- [ ] Cache-first lookup
- [ ] Balansen-pagina toont EUR-kolom totaal
- [ ] Test: happy / unmapped asset
- [ ] /review groen → merge

### Blok 3.C — Dagelijkse close voor peildatums
**Branch:** feature/3-c-snapshot-pricing — **Model:** Sonnet
- [ ] Pagina "Jaaroverzicht" met jaar-keuze
- [ ] Per token: hoeveelheid × close
- [ ] Totaal portfolio EUR
- [ ] Test: happy / leeg jaar
- [ ] /review groen → merge

### Blok 3.D — Werkelijk-rendement basis
**Branch:** feature/3-d-realized-rendement — **Model:** Opus
- [ ] Per token: open × prijs_1jan, close × prijs_31dec
- [ ] Som inflows/outflows × prijs op transactiemoment
- [ ] (Voorlopige) classificatie: TRANSFER mee, GAS niet
- [ ] Disclaimer in UI
- [ ] Test: 1-token jaar / start+end jaar / regressie balansen
- [ ] /review groen → merge

### Fase 3 afgerond
- [ ] `/ultrareview` op fase 3

---

## Fase 4 — Schema-unificatie + Bitcoin

### Kickoff (Opus)
- [ ] Scope-analyse + vragenlijst
- [ ] Blok-uitwerking bevestigd

### Blok 4.A — Schema migratie naar source-kolom
**Branch:** feature/4-a-schema-source — **Model:** Opus
- [ ] Schema versie 2 of nieuwe migration
- [ ] Bestaande on-chain rows behouden source-tag
- [ ] Index op (wallet_id, source)
- [ ] CLAUDE.md sectie 6 bijgewerkt
- [ ] Test: bestaande balansen onveranderd / lege DB schoon
- [ ] /review groen → merge

### Blok 4.B — Bitcoin HTTP-laag
**Branch:** feature/4-b-btc-api — **Model:** Opus
- [ ] core/api_btc.py met fetch_btc_txs
- [ ] Paginatie + rate-limit
- [ ] Geen DB-toegang
- [ ] Test: happy / leeg adres
- [ ] /review groen → merge

### Blok 4.C — Bitcoin fetcher + UI
**Branch:** feature/4-c-btc-fetch — **Model:** Sonnet
- [ ] core/fetcher_btc.py
- [ ] BTC adres-veld in pages/01_wallets.py
- [ ] Importeren-pagina toont BTC-resultaat apart
- [ ] BTC verschijnt op balansen + ledger
- [ ] Test: happy / xpub-edge (uit scope MVP) / regressie EVM
- [ ] /review groen → merge

### Fase 4 afgerond
- [ ] `/ultrareview` op fase 4

---

## Fase 5 — Beurzen (CSV-import)

### Kickoff (Opus)
- [ ] Scope-analyse + vragenlijst
- [ ] Blok-uitwerking bevestigd

### Blok 5.A — Bitvavo CSV-importer
**Branch:** feature/5-a-bitvavo-import — **Model:** Sonnet
- [ ] CSV-upload op pages/06_imports.py
- [ ] BUY/SELL → twee transactions
- [ ] Fees als aparte rows
- [ ] Idempotent
- [ ] Test: happy / dubbele upload / unmapped token
- [ ] /review groen → merge

### Blok 5.B — Kraken CSV-importer
**Branch:** feature/5-b-kraken-import — **Model:** Sonnet
- [ ] Parser voor ledgers.csv format
- [ ] Trades + fees correct
- [ ] Idempotent
- [ ] Test: happy / dubbele / edge
- [ ] /review groen → merge

### Blok 5.C — Coinbase CSV-importer
**Branch:** feature/5-c-coinbase-import — **Model:** Sonnet
- [ ] Parser voor Coinbase format
- [ ] Trades + fees correct
- [ ] Idempotent
- [ ] Test: happy / dubbele / edge
- [ ] /review groen → merge

### Fase 5 afgerond
- [ ] `/ultrareview` op fase 5

---

## Fase 6 — Transactie-classificatie

### Kickoff (Opus)
- [ ] Scope-analyse + vragenlijst
- [ ] Blok-uitwerking bevestigd

### Blok 6.A — DEX-router register + SWAP-detectie
**Branch:** feature/6-a-dex-routers — **Model:** Opus
- [ ] DEX_ROUTERS per chain
- [ ] classify_transaction(row)
- [ ] Backfill-functie
- [ ] Test: Uniswap swap / non-DEX transfer / regressie bridges
- [ ] /review groen → merge

### Blok 6.B — Linked_id voor swap-paren
**Branch:** feature/6-b-swap-pairs — **Model:** Opus
- [ ] linked_id kolom op transactions
- [ ] Heuristiek: zelfde tx_hash, SWAP_IN+SWAP_OUT → koppelen
- [ ] Ledger toont gekoppelde swap als één regel
- [ ] Test: simpele swap / multi-hop swap
- [ ] /review groen → merge

### Blok 6.C — REWARD-detectie
**Branch:** feature/6-c-rewards — **Model:** Sonnet
- [ ] REWARD_CONTRACTS per chain
- [ ] Inflow van reward-contract → REWARD
- [ ] Werkt voor xOPN-distributies + BEAM ATH/WMC
- [ ] Test: happy / niet-reward inflow uit zelfde contract (handmatige override)
- [ ] /review groen → merge

### Fase 6 afgerond
- [ ] `/ultrareview` op fase 6

---

## Fase 7 — Delta reconcile-flow

### Kickoff (Opus)
- [ ] Scope-analyse + vragenlijst
- [ ] Blok-uitwerking bevestigd

### Blok 7.A — Delta CSV parser
**Branch:** feature/7-a-delta-parser — **Model:** Sonnet
- [ ] Parser leest Delta CSV-format
- [ ] Output: dict-lijst zonder DB-writes
- [ ] Test: happy / leeg
- [ ] /review groen → merge

### Blok 7.B — Match-algoritme
**Branch:** feature/7-b-delta-match — **Model:** Opus
- [ ] match(delta_row, db_rows) met tolerantie ±24h, ±0,5%
- [ ] Deterministisch + testbaar
- [ ] 95%+ matches op echte Delta-export
- [ ] Test: happy / dubbele match resolve / no-match
- [ ] /review groen → merge

### Blok 7.C — Approval-UI voor unmatched
**Branch:** feature/7-c-delta-ui — **Model:** Sonnet
- [ ] Pagina pages/07_delta.py met accept/reject
- [ ] Accepteer → source=delta_manual rij
- [ ] Verwerp → niets in DB
- [ ] Test: import met match + unmatched / dubbele upload
- [ ] /review groen → merge

### Fase 7 afgerond
- [ ] `/ultrareview` op fase 7

---

## Fase 8 — Belastingrapport

### Kickoff (Opus)
- [ ] Scope-analyse + vragenlijst
- [ ] Blok-uitwerking bevestigd

### Blok 8.A — Box 3 forfait (waarde per 1 januari)
**Branch:** feature/8-a-box3-forfait — **Model:** Sonnet
- [ ] core/tax.py + pages/08_belasting.py
- [ ] Per jaar: totaal EUR per 1 jan
- [ ] Onderverdeling per token
- [ ] Test: happy / jaar vóór eerste tx
- [ ] /review groen → merge

### Blok 8.B — Werkelijk rendement
**Branch:** feature/8-b-werkelijk-rendement — **Model:** Opus
- [ ] Per token per jaar: open, close, in (BUY+REWARD), out (SELL), netto rendement
- [ ] Aggregaat over hele portfolio
- [ ] Werkt over meerdere jaren
- [ ] Test: bekend portfolio / alleen-swaps jaar / REWARD als inkomst
- [ ] /review groen → merge

### Blok 8.C — Kostprijs WMA (gerealiseerd resultaat)
**Branch:** feature/8-c-wma-kostprijs — **Model:** Opus
- [ ] WMA kostprijs per asset over tijd
- [ ] Gerealiseerd resultaat per verkoop
- [ ] Aggregaat per jaar
- [ ] Test: bekend voorbeeld / short (markeer ongeldig) / REWARD als basis
- [ ] /review groen → merge

### Blok 8.D — PDF export
**Branch:** feature/8-d-pdf — **Model:** Sonnet
- [ ] PDF per jaar met forfait + rendement + kostprijs
- [ ] Download-knop
- [ ] Test: PDF opent in Preview / veel tokens (multi-page)
- [ ] /review groen → merge

### Fase 8 afgerond
- [ ] `/ultrareview` op fase 8
- [ ] Project compleet — eindcheck volledige flow met echte data
