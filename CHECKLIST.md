# Checklist — Crypto Tracker

Spiegelt [project_spec.md](project_spec.md). Eén checkbox per blok-acceptatiecriterium.
Afvinken = gedaan + getest + gemerged naar main.

Volgorde van werken: kickoff (Opus) per fase → blokken sequentieel → fase-review (`/ultrareview`).

## Actuele status

Laatst bijgewerkt: 2026-05-05.

| Fase | Naam | Status |
|---|---|---|
| Setup | Projectbasis | ✅ Afgerond |
| 1 | On-chain MVP afronden | ✅ Afgerond |
| 2 | Ledger-pagina (transactiehistorie) | ✅ Afgerond |
| 3 | EUR-prijslaag (CoinGecko + CMC fallback) | ◐ 3.1 t/m 3.10 lokaal afgerond, klaar voor review/merge |
| 4 | Schema-unificatie + Bitcoin | ☐ Open |
| 5 | Beurzen (CSV-import) | ☐ Open |
| 6 | Transactie-classificatie | ☐ Open |
| 7 | Delta reconcile-flow | ☐ Open |
| 8 | Belastingrapport | ☐ Open |

---

## Setup

- [x] Nieuwe map aangemaakt (`crypto-tracker/`)
- [x] Git repo geïnitialiseerd
- [x] uv project + dependencies (streamlit, httpx, python-dotenv)
- [x] AGENTS.md/CLAUDE.md + CURRENT.md + project_spec.md + REVIEW.md geschreven
- [x] GitHub repo aangemaakt en gekoppeld
- [x] `.env` aanmaken met API keys (`cp .env.example .env`)

---

## Fase 1 — On-chain MVP afronden

> Kickoff: Opus 4.7, 2026-04-30. Blokken 1.A–1.D afgerond.

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
- [x] core/fetcher.py < 400 regels
- [x] Wrap-reconciliation logica geëxtraheerd naar eigen module
- [x] main.py weg of vervangen door zinvolle entrypoint
- [x] Bestaande publieke API ongewijzigd
- [x] Test: happy path / wrap-edge / regressie incremental
- [x] /review groen → merge

### Blok 1.B — ETH 96 dataverlies herstellen
**Branch:** geen — operationele actie — **Model:** Sonnet
- [x] wallet_chain_state reset (main + ethereum + txlist)
- [x] Re-fetch uitgevoerd
- [x] On-chain verificatie ETH/main toont ✅
- [x] Test: geen dubbele transacties / andere wallets onaangetast

### Blok 1.C — PEAR/Arbitrum fetch debuggen
**Branch:** feature/1-c-pear-debug — **Model:** Opus
- [x] Root cause schriftelijk vastgelegd
- [x] PEAR + stPEAR zichtbaar in token-review na fetch
- [x] stPEAR auto-accepted zodra PEAR accepted
- [x] Test: happy path / leeg / regressie andere chains
- [x] /review groen → merge

### Blok 1.D — BEAM node staking saldo tonen
**Branch:** feature/1-d-beam-staking — **Model:** Opus
- [x] BEAM-staking-positie zichtbaar op balansen-pagina
- [x] Reproduceerbare berekening, formule in code gedocumenteerd
- [x] Werkt zonder volledige re-fetch
- [x] Test: 5M zichtbaar / lege wallet / regressie andere balansen
- [x] /review groen → merge

### Blok 1.E — Memory + spec opschonen
**Branch:** feature/1-e-memory-cleanup — **Model:** Haiku
- [x] WIP staked-tokens memory weg
- [x] project_open_issues.md gemarkeerd "afgehandeld"
- [x] CHECKLIST in lijn met spec
- [x] Test: geen verwijzingen naar oude memory / project_later_list intact

### Fase 1 afgerond
- [x] `/ultrareview` op fase 1 (alle blokken samen)
- [x] Alle 3 open issues gesloten

### Nagekomen hardening — scam-token filtering
- [x] Token review gebruikt contract-aware keys i.p.v. alleen ticker/symbool
- [x] Scam/verdacht/onbekend/veilig status wordt automatisch opgeslagen
- [x] Balansen en Transacties joinen op dezelfde contract-aware token_key
- [x] Test: same-symbol scam / migratie / user override / regressie ledger

---

## Fase 2 — Ledger-pagina (transactiehistorie)

### Kickoff (Opus)
- [x] Scope-analyse + vragenlijst
- [x] Blok-uitwerking bevestigd

### Blok 2.A — Pagina "Transacties"
**Branch:** feature/2-a-ledger-page — **Model:** Sonnet
- [x] Filter wallet (incl. "alle"), chain, token
- [x] Sorteer op datum (default desc)
- [x] Kolommen: datum, type, bedrag, asset, tx_hash (kort), bron-endpoint
- [x] Etherscan-link per rij
- [x] Test: happy / leeg / regressie
- [x] /review groen → merge

### Blok 2.B — Export naar CSV
**Branch:** feature/2-b-ledger-export — **Model:** Haiku
- [x] Download-knop levert CSV met huidige filter
- [x] Bestandsnaam bevat wallet/token/datum
- [x] Test: happy / lege filter / regressie
- [x] /review groen → merge

### Fase 2 afgerond
- [x] `/ultrareview` op fase 2

---

## Fase 3 — EUR-prijslaag (CoinGecko + CoinMarketCap fallback)

> Bouwplan: `plans/plan-fase-3.md` is canoniek; externe mirrors zijn alleen kopieën.
> Huidige taak: expliciete review/merge of fase 4 kickoff.
> Status: subblokken 3.1 t/m 3.10 lokaal geïmplementeerd en getest; blokken blijven open tot review/merge.

### Kickoff (Opus)
- [x] Scope-analyse + vragenlijst
- [x] Blok-uitwerking bevestigd

### Blok 3.A — price_cache schema + CoinGecko HTTP-laag + mapping
**Branch:** feature/3-a-prices-core — **Model:** Opus
> Voortgang 2026-05-04: subblokken 3.1 t/m 3.8 zijn lokaal afgerond en getest met gerichte tests, de volledige unittest-suite en een lokale Streamlit-start.
- [ ] Tabellen `price_cache` en `price_fetch_log` ontstaan na `init_db()`, idempotent
- [ ] `price_cache` gebruikt `PRIMARY KEY (coingecko_id, date)`, niet ticker/symbool
- [ ] Index `idx_price_cache_date` bestaat
- [ ] `core/coingecko.py` bevat `fetch_price`, `fetch_price_range`, `fetch_current_prices`, `calls_today`
- [ ] Cache-first: tweede call voor `(coingecko_id, date)` doet geen HTTP-call
- [ ] Bulk-fetch via `market_chart`: één call per token/jaar, geen per-dag `/history` loop als default
- [ ] Multi-asset huidige prijzen via `/simple/price`: één call voor N tokens
- [ ] Daily budget-guard via `COINGECKO_DAILY_CALL_BUDGET` + `price_fetch_log`
- [ ] Rate-limit 429 wordt opgevangen met retry, max 5
- [ ] Sleep ≥ 2,5s tussen sequential API-calls
- [ ] Token-identiteit staat centraal in `core/token_identity.py`: `(chain, contract_address | None) → canonical_asset → coingecko_id`
- [ ] `coingecko_id_for()` geeft alleen directe/equivalente price ids; xOPN/stPEAR hebben staking-policy, geen directe prijsredirect
- [ ] Onbekende/scam/LP tokens zonder mapping geven `None`, geen stille symbol-match
- [ ] `.env.example` bevat `COINGECKO_API_KEY=` en `COINGECKO_DAILY_CALL_BUDGET=300`
- [ ] Geen UI-wijzigingen in dit blok
- [ ] Test: happy / cache-hit / bulk fetch / multi-asset current / wrapper redirect / onbekende token / rate limit / budget-guard
- [ ] /review groen → merge

### Blok 3.B — Spotprijs op transactiemoment (balansen + ledger)
**Branch:** feature/3-b-spot-pricing — **Model:** Sonnet
- [ ] `core/prices.py` met `eur_value`, `eur_balances_today`, `eur_transactions`
- [ ] Balansen-pagina toont kolom "Waarde (EUR)" + totaal onder de tabel
- [ ] Balansen-pagina gebruikt `fetch_current_prices` met één multi-asset call
- [ ] Transacties-pagina toont kolom "EUR (op tx-datum)"
- [ ] Transacties-pagina prefetcht per `(coingecko_id, jaar)` één keer, geen N+1 calls
- [ ] CSV-export bevat extra EUR-kolom
- [ ] Ontbrekende prijs toont "—", geen exception
- [ ] Wrappers (xOPN, stPEAR) worden niet naïef als gewone tokens geprijsd; stake/unstake-eventlogica volgt later
- [ ] Totaal-EUR markeert "(deels onbekend)" als er onbekende EUR-cellen zijn
- [ ] Test: happy / wrapper / missende mapping / ledger 2026 / CSV-export / cached regressie
- [ ] /review groen → merge

### Blok 3.C — Dagelijkse close voor peildatums (Jaaroverzicht)
**Branch:** feature/3-c-snapshot-pricing — **Model:** Sonnet
- [ ] `core/prices.py` uitgebreid met `balance_at(date)` en `snapshot_for_year(year)`
- [ ] Pagina `pages/05_jaaroverzicht.py` met dropdown jaar
- [ ] Jaarlijst loopt van eerste tx-jaar tot huidig jaar
- [ ] Lazy per jaar: alleen geselecteerd jaar raakt de API
- [ ] Tabel: token | hoeveelheid 1-1 | prijs 1-1 | EUR 1-1 | hoeveelheid 31-12 | prijs 31-12 | EUR 31-12
- [ ] Totaal portfolio EUR per peildatum + "(deels onbekend)" indicator
- [ ] Bulk-fetch: één `market_chart` call per token per jaar
- [ ] Pre-flight budgetmelding: "Dit kost X calls, Y/300 vandaag al gebruikt" + doorgaan-knop
- [ ] Tweede keer hetzelfde jaar openen doet 0 calls
- [ ] Test: happy 2026 eerst / lazy 2025 daarna / jaar vóór eerste tx / geen EUR-prijs / cache / budget-guard
- [ ] /review groen → merge

### Blok 3.D — Werkelijk-rendement basis
**Branch:** feature/3-d-realized-rendement — **Model:** Opus
> Voortgang 2026-05-05: subblok 3.9 en 3.10 zijn lokaal afgerond en getest met de volledige unittest-suite (103 tests). Checkboxes blijven open tot review/merge volgens deze checklist-afspraak.
- [ ] Module `core/rendement.py` met `compute_year(year) -> list[dict]`
- [ ] Per `(wallet, chain, token)`: open_eur, close_eur, in_eur, out_eur, gas_eur, netto_eur
- [ ] Netto formule: `(close_eur - open_eur) - (in_eur - out_eur)`
- [ ] GAS_FEE is info-kolom en telt niet mee in de formule
- [ ] Aggregaat-totaal onderaan de tabel
- [ ] `incomplete=True` markeert rij als "(deels onbekend)"
- [ ] Jaaroverzicht-pagina toont sectie "Werkelijk rendement"
- [ ] Disclaimer in UI: voorlopige berekening, classificatie wordt verfijnd in fase 6/8
- [ ] Geen extra API-calls boven 3.C-budget; cache wordt hergebruikt
- [ ] Test: 1 token buy+sell / token gestart en verkocht zelfde jaar / saldo zonder tx / missende prijs / regressie balansen
- [ ] /review groen → merge

### Fase 3 afgerond
> Lokale fase-review 2026-05-05: tests/compile groen; review-fix voor nul-balans peildatum in `snapshot_for_year()` toegevoegd. `/ultrareview`/merge nog niet uitgevoerd.
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

### Blok 6.D — Staking position reconstruction
**Branch:** feature/6-d-staking-positions — **Model:** Opus
- [ ] Herkent stake-open: underlying out + wrapper in (`-100 OPN` + `+80 xOPN`)
- [ ] Positiegrondslag blijft de verstuurde underlying, niet het wrapper-aantal
- [ ] Herkent unstake/close: wrapper out + underlying in
- [ ] Splitst unstake in principal return + yield/rendement (`110 OPN` terug op `100 OPN` inleg = `10 OPN` yield)
- [ ] Ondersteunt partial unstake en meerdere open posities conservatief
- [ ] xOPN/stPEAR worden niet als gewone tokens geprijsd in jaaroverzicht/rendement
- [ ] Oude xGET/staked xGET → xOPN/OPN flow staat als onderzoeks-/migratiecase
- [ ] Test: happy / partial unstake / open positie op peildatum / regressie gewone transfers
- [ ] /review groen → merge

### Blok 6.E — Handmatige waarderingsstatus voor dead/worthless tokens
**Branch:** feature/6-e-token-valuation-status — **Model:** Opus
- [ ] Token review ondersteunt status `active` / `unknown` / `manual_zero` / `worthless`
- [ ] `manual_zero`/`worthless` heeft optionele ingangsdatum, reden en bron/notitie
- [ ] Geen automatische prijsfallback naar 0 bij ontbrekende marktprijs
- [ ] Balansen/Jaaroverzicht tonen duidelijk "handmatig op nul gezet" vanaf ingangsdatum
- [ ] Historische inleg/aanschafwaarde blijft zichtbaar
- [ ] Test: dead token vanaf datum 0 / vóór datum normale prijs of "—" / unknown blijft "—"
- [ ] /review groen → merge

### Blok 6.F — Pre-market/private-sale cost basis
**Branch:** feature/6-f-private-sale-cost-basis — **Model:** Opus
- [ ] Herkent of laat handmatig koppelen: betaling out ↔ pre-market token in
- [ ] Kostprijs ontvangen token wordt gebaseerd op waarde van verstuurde tegenprestatie
- [ ] Ondersteunt EUR/stablecoin/crypto betaling met prijs op betaaldatum
- [ ] Token zonder marktprijs krijgt geen CoinGecko fallback, maar kan wel cost basis krijgen
- [ ] Jaaroverzicht/rendement tonen marktwaarde en cost basis apart
- [ ] Audit trail/notitie bij handmatige koppeling
- [ ] Test: NCKS/private-sale happy / crypto betaling / geen koppeling blijft incompleet / regressie gewone swaps
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

### Blok 8.E — Dead/worthless tokens in belastingrapportage
**Branch:** feature/8-e-worthless-token-reporting — **Model:** Opus
- [ ] Rapport gebruikt waarderingsstatus uit fase 6
- [ ] `manual_zero`/`worthless` telt vanaf ingangsdatum met eindwaarde EUR 0
- [ ] Rapport toont reden/bron/notitie en markeert dit als handmatige waardering
- [ ] Werkelijk-rendement overzicht laat historische inleg én afwaardering naar 0 zien
- [ ] Geen fiscale conclusie automatisch forceren; aannames blijven zichtbaar
- [ ] Test: dead token met historische inleg / peildatum vóór en na ingangsdatum / PDF-vermelding
- [ ] /review groen → merge

### Fase 8 afgerond
- [ ] `/ultrareview` op fase 8
- [ ] Project compleet — eindcheck volledige flow met echte data
