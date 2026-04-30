# Project Spec — Crypto Portfolio Tracker

## Doel

Een veilige, lokaal draaiende applicatie die al je cryptocurrency-transacties bijhoudt
over meerdere wallets en exchanges. De app geeft op elk moment inzicht in de totale
waarde van je portfolio in euro's, en genereert automatisch fiscale jaaroverzichten
voor de Belastingdienst (Box 3 forfait én werkelijk rendement). Alles draait op je
eigen machine — geen cloud, geen gedeelde data, geen private keys.

---

## Werkwijze

Het project is opgebouwd in **fasen**. Elke fase bestaat uit **blokken**: kleine,
zelfstandig mergebare stappen met eigen branch, review en test. Een blok is af
zodra de acceptatiecriteria + test-scenarios groen zijn én de review goed is.

### Kickoff per fase (Opus)

Aan het begin van elke fase doorloopt Claude (Opus) dit protocol vóór er code
geschreven wordt:

1. **Scope-analyse** — relevante code, doel van de fase en gerelateerde memory lezen.
2. **Vragenlijst** — open vragen stellen tot 95% helder is.
3. **Blok-uitwerking** — per blok: doel, files, acceptatiecriteria, test-scenarios,
   aanbevolen model.
4. **Risico's & afhankelijkheden** — wat moet eerder klaar? Welk schema verandert?
5. **Akkoord** — gebruiker bevestigt blok-indeling vóór er gebouwd wordt.

### Blok-werkflow

```
1. Branch:  git checkout -b feature/x-y-naam
2. Bouwen:  per acceptatiecriterium één commit
3. Testen:  alle test-scenarios handmatig doorlopen
4. Review:  /review (Sonnet, snel) — fix bevindingen
5. Merge:   PR maken, mergen naar main, branch verwijderen
```

Aan het eind van elke fase: `/ultrareview` (Opus, grondig) op alle blokken samen.

### Model-tiering

| Model | Wanneer | Voorbeeld |
|---|---|---|
| **Opus 4.7** | Architectuur, schemawijzigingen, complexe algoritmes, fase-kickoff, security review | Schema-migratie, kostprijs WMA, Delta-match algoritme |
| **Sonnet 4.6** | Standaard implementatie binnen bekend patroon, UI-pagina's, code review per blok, refactors | CSV-importer, Streamlit-pagina, file-split |
| **Haiku 4.5** | Mechanische taken volgens een al uitgewerkt plan: file moves, simpele tests, doc-updates | Memory opschonen, MD-spiegels updaten, regex-vervangingen |

Per blok staat in deze spec welk model aanbevolen is. Modelwissel doe je via `/model`.

### Sjabloon per blok

```markdown
### Blok X.Y — [naam]

**Doel:** Eén zin: wat moet werken na dit blok.
**Aanbevolen model:** Opus / Sonnet / Haiku — kort waarom.
**Branch:** feature/x-y-naam
**Wijzigt:** verwachte bestanden.
**Afhankelijk van:** eerdere blokken die af moeten zijn.

**Acceptatiecriteria:**
- [ ] ...

**Test-scenarios:**
1. **Happy path:** [stappen] → [verwacht resultaat]
2. **Edge case:** [stappen] → [verwacht resultaat]
3. **Regressie:** [bestaande feature die niet mag breken]

**Review:** /review (per blok) — /ultrareview komt aan einde van fase.
**Merge:** zodra acceptatie + test + review groen.
```

---

## Fase-overzicht

| Fase | Naam | Status |
|---|---|---|
| 1 | On-chain MVP afronden | ✅ Afgerond |
| 2 | Ledger-pagina (transactiehistorie) | ☐ Open |
| 3 | EUR-prijslaag (CoinGecko) | ☐ Open |
| 4 | Schema-unificatie + Bitcoin | ☐ Open |
| 5 | Beurzen (CSV-import) | ☐ Open |
| 6 | Transactie-classificatie | ☐ Open |
| 7 | Delta reconcile-flow | ☐ Open |
| 8 | Belastingrapport | ☐ Open |

---

## Fase 1 — On-chain MVP afronden

**Doel:** Alle 3 open issues gesloten + code-hygiëne op orde, zodat fase 1 een
stabiele basis is voor de rest.

### Blok 1.A — fetcher.py refactor + main.py opruimen

**Doel:** [core/fetcher.py](core/fetcher.py) onder de 400-regel limiet (CLAUDE.md);
ongebruikte [main.py](main.py) opruimen.
**Aanbevolen model:** Sonnet — pure refactor, geen ontwerpkeuzes.
**Branch:** feature/1-a-fetcher-refactor
**Wijzigt:** core/fetcher.py, mogelijk core/wrap_reconcile.py (nieuw), main.py.

**Acceptatiecriteria:**
- [ ] core/fetcher.py < 400 regels
- [ ] Wrap-reconciliation logica (sectie 4 + 4b) geëxtraheerd naar eigen module
- [ ] main.py weg of vervangen door zinvolle entrypoint
- [ ] Bestaande publieke API (`fetch_wallet`, `fetch_all`) ongewijzigd

**Test-scenarios:**
1. **Happy path:** `uv run streamlit run app.py` → Importeren-pagina werkt, fetch loopt door zonder errors.
2. **Edge case:** WETH-mint reconciliatie blijft werken (deposit zonder Transfer-event → synthese rij).
3. **Regressie:** Tweede fetch geeft 0 nieuwe + N skipped (incrementeel) blijft werken.

### Blok 1.B — ETH 96 dataverlies herstellen

**Doel:** Main-wallet ETH-saldo terug van 96 naar 0,107 ETH (on-chain waarheid).
**Aanbevolen model:** Sonnet — diagnose + schema-migratie + verificatie.
**Branch:** feature/1-b-eth-dedup-fix
**Wijzigt:** core/db.py (constraint + migratie), core/fetcher.py (dedup key), CLAUDE.md, REVIEW.md.

**Root cause:** Niet een cursor-bug maar een dedup-bug. `UNIQUE(tx_hash, wallet_id)` blokkeerde
txlist TRANSFER_OUTs wanneer dezelfde outer tx_hash ook in tokentx stond (bijv. "koop tokens
met ETH" via Uniswap). 119 TRANSFER_OUTs geblokkeerd → 95,96 ETH te hoog computed.

**Acceptatiecriteria:**
- [x] `UNIQUE(tx_hash, wallet_id, source)` in schema + migratie in `_migrate_tx_dedup_constraint`
- [x] In-memory dedup in fetcher gebruikt `(tx_hash, source)` als key
- [x] txlist cursor gereset en re-fetch uitgevoerd
- [x] On-chain verificatie ETH/main toont ✅
- [x] CLAUDE.md Les 1 en REVIEW.md bijgewerkt

**Test-scenarios:**
1. **Happy path:** re-fetch → TRANSFER_OUT count ~202, ETH computed ≈ 0,107.
2. **Edge case:** bestaande tokentx-rijen blijven intact na schema-migratie.
3. **Regressie:** andere wallets/chains blijven onaangetast.

### Blok 1.C — PEAR/Arbitrum fetch debuggen

**Doel:** PEAR en stPEAR verschijnen in token-review en (na accept) op balansen-pagina.
**Aanbevolen model:** Opus — diagnose vereist redenering over DB-state + fetch-flow.
**Branch:** feature/1-c-pear-debug
**Wijzigt:** waarschijnlijk niets in code; mogelijk een fix in fetch-flow of UI.

**Acceptatiecriteria:**
- [ ] Root cause schriftelijk vastgelegd (geen blinde fix)
- [ ] PEAR + stPEAR zichtbaar in token-review na fetch
- [ ] stPEAR auto-accepted zodra PEAR accepted is

**Test-scenarios:**
1. **Happy path:** Importeren → PEAR verschijnt → accept → stPEAR ook accepted → balans zichtbaar.
2. **Edge case:** wallet zonder Arbitrum-activiteit geeft geen errors.
3. **Regressie:** andere chains blijven werken.

### Blok 1.D — BEAM node staking saldo tonen

**Doel:** Echte BEAM-saldo (5M gestaked + 0,7 liquid) zichtbaar op balansen-pagina.
**Aanbevolen model:** Opus — ontwerpkeuze (live-query vs. opslag), niet-triviaal.
**Branch:** feature/1-d-beam-staking
**Wijzigt:** core/staking.py (uitbreiden), pages/03_balances.py.

**Acceptatiecriteria:**
- [ ] BEAM-staking-positie zichtbaar op balansen-pagina
- [ ] Reproduceerbare berekening (formule gedocumenteerd in code)
- [ ] Werkt zonder volledige re-fetch van historische txlist

**Test-scenarios:**
1. **Happy path:** Balansen-pagina → BEAM ≈ 5.000.003.
2. **Edge case:** wallet zonder BEAM-staking toont geen extra rij.
3. **Regressie:** andere balansen onveranderd.

### Blok 1.E — Memory + spec opschonen

**Doel:** Stale memory weg, nieuwe workflow vastgelegd, alle docs consistent.
**Aanbevolen model:** Haiku — mechanische update.
**Branch:** feature/1-e-memory-cleanup
**Wijzigt:** memory/project_open_issues.md, CHECKLIST.md, project_spec.md.

**Acceptatiecriteria:**
- [ ] WIP staked-tokens memory weg (feature is klaar)
- [ ] project_open_issues.md gemarkeerd "afgehandeld in fase 1"
- [ ] CHECKLIST.md spiegelt deze spec

**Test-scenarios:**
1. **Happy path:** geen verwijzingen meer naar oude WIP-bestanden in MEMORY.md.
2. **Regressie:** project_later_list.md blijft intact.

---

## Fase 2 — Ledger-pagina (transactiehistorie)

**Doel:** Per wallet+token alle transacties zien (datum, bedrag, type, tx_hash).
Nuttig voor handmatige inspectie en als basis voor latere classificatie.

### Blok 2.A — Pagina "Transacties"

**Doel:** Nieuwe Streamlit-pagina met filters (wallet, chain, token) en tabel.
**Aanbevolen model:** Sonnet — standaard Streamlit-pagina.
**Branch:** feature/2-a-ledger-page
**Wijzigt:** pages/04_transacties.py (nieuw).

**Acceptatiecriteria:**
- [ ] Filter wallet (incl. "alle"), chain, token
- [ ] Sorteer op datum (default desc)
- [ ] Kolommen: datum, type, bedrag, asset, tx_hash (kort), bron-endpoint
- [ ] Etherscan-link per rij (klikbaar via tx_hash)

**Test-scenarios:**
1. **Happy path:** filter wallet+token → toont alle transacties.
2. **Edge case:** wallet zonder transacties → "geen resultaten".
3. **Regressie:** andere pagina's onveranderd.

### Blok 2.B — Export naar CSV

**Doel:** Lijst exporteren voor externe analyse / archief.
**Aanbevolen model:** Haiku — kleine toevoeging op bestaande pagina.
**Branch:** feature/2-b-ledger-export
**Wijzigt:** pages/04_transacties.py.

**Acceptatiecriteria:**
- [ ] Download-knop levert CSV met huidige filter
- [ ] Bestandsnaam bevat wallet/token/datum

**Test-scenarios:**
1. **Happy path:** filter → export → CSV opent correct in numbers/excel.
2. **Edge case:** lege filter resulteert in lege CSV met header.

---

## Fase 3 — EUR-prijslaag (CoinGecko)

**Doel:** Spotprijzen op transactiemoment + dagelijkse close voor peildatums.
Voorwaarde voor latere validatie van CEX-imports en voor belastingrapport.

### Blok 3.A — price_cache schema + CoinGecko HTTP-laag

**Doel:** Prijsdata-bron + opslag, zonder UI.
**Aanbevolen model:** Opus — schema-keuze + API-rate-limit ontwerp.
**Branch:** feature/3-a-prices-core
**Wijzigt:** core/db.py (price_cache tabel), core/coingecko.py (nieuw).

**Acceptatiecriteria:**
- [ ] Tabel `price_cache (asset, date, eur, source, fetched_at)` UNIQUE(asset, date)
- [ ] `core/coingecko.py` met `fetch_price(asset, date) -> Decimal | None`
- [ ] Rate-limit (free tier ~30/min) afgevangen met retries
- [ ] Mapping `asset_symbol → coingecko_id` (handmatig dict, niet auto)

**Test-scenarios:**
1. **Happy path:** fetch_price("ETH", "2024-01-01") → ~2000 EUR opgeslagen.
2. **Edge case:** onbekend symbool → None, geen crash.
3. **Edge case:** rate limit → retry, uiteindelijk succes.

### Blok 3.B — Spotprijs op transactiemoment

**Doel:** Per transactie EUR-waarde berekenen via close-prijs van die dag.
**Aanbevolen model:** Sonnet — toevoeging op bestaande pagina's.
**Branch:** feature/3-b-spot-pricing
**Wijzigt:** core/prices.py (nieuw, helper), pages/03_balances.py.

**Acceptatiecriteria:**
- [ ] `eur_value(asset, date, amount)` helper
- [ ] Cache-first: alleen API call als (asset, date) ontbreekt
- [ ] Balansen-pagina toont EUR-kolom totaal

**Test-scenarios:**
1. **Happy path:** balans 1 ETH → ~2000 EUR getoond.
2. **Edge case:** asset zonder coingecko mapping → "—" tonen, geen error.

### Blok 3.C — Dagelijkse close voor peildatums

**Doel:** Voor 1 januari per jaar: alle gehouden assets × close = portfolio-waarde.
**Aanbevolen model:** Sonnet.
**Branch:** feature/3-c-snapshot-pricing
**Wijzigt:** core/prices.py, pages/05_jaaroverzicht.py (nieuw).

**Acceptatiecriteria:**
- [ ] Pagina "Jaaroverzicht": kies jaar → toont waarde per 1 jan en 31 dec
- [ ] Per token: hoeveelheid × close
- [ ] Totaal portfolio EUR

**Test-scenarios:**
1. **Happy path:** jaar 2024 → bedragen kloppen met handmatige check.
2. **Edge case:** jaar zonder activiteit → lege tabel, geen error.

### Blok 3.D — Werkelijk-rendement basis

**Doel:** Per token per jaar: begin/eind balans + alle buys/sells in dat jaar.
**Aanbevolen model:** Opus — fiscaal correct opzetten is risicogevoelig.
**Branch:** feature/3-d-realized-rendement
**Wijzigt:** core/rendement.py (nieuw), pages/05_jaaroverzicht.py.

**Acceptatiecriteria:**
- [ ] Per token: open_balance × prijs_1jan, close_balance × prijs_31dec
- [ ] Som inflows en outflows × prijs op transactiemoment
- [ ] (Voorlopige) classificatie: TRANSFER_IN/OUT meetellen, GAS_FEE niet
- [ ] Disclaimer in UI: classificatie nog ruw — definitief in fase 6

**Test-scenarios:**
1. **Happy path:** jaar met 1 token, 1 buy, 1 sell → cijfers kloppen handmatig.
2. **Edge case:** token gestart en geheel verkocht in zelfde jaar.
3. **Regressie:** balansen-pagina toont nog steeds totalen correct.

---

## Fase 4 — Schema-unificatie + Bitcoin

**Doel:** `transactions` tabel klaarmaken voor meerdere bronnen (on-chain EVM, BTC,
later beurzen + Delta) en de eerste niet-EVM bron toevoegen.

### Blok 4.A — Schema migratie naar source-kolom

**Doel:** `transactions.source` opwaarderen tot een enum-achtige kolom die bron
identificeert (`onchain_etherscan`, `bitcoin`, etc.).
**Aanbevolen model:** Opus — schemawijziging raakt alle queries.
**Branch:** feature/4-a-schema-source
**Wijzigt:** core/db.py, alle queries in core/.

**Acceptatiecriteria:**
- [ ] Schema bijgewerkt (versie 2) of nieuwe migration als reset niet acceptabel
- [ ] Bestaande on-chain rows behouden hun source-tag
- [ ] Index op (wallet_id, source) voor performance
- [ ] Documentatie in CLAUDE.md sectie 6

**Test-scenarios:**
1. **Happy path:** bestaande balansen onveranderd na migratie.
2. **Edge case:** lege DB → schema bouwt clean op.
3. **Regressie:** alle pagina's blijven werken.

### Blok 4.B — Bitcoin HTTP-laag

**Doel:** mempool.space of Blockstream als bron voor BTC-transacties.
**Aanbevolen model:** Opus — nieuwe API, eigen pagineerbeleid.
**Branch:** feature/4-b-btc-api
**Wijzigt:** core/api_btc.py (nieuw).

**Acceptatiecriteria:**
- [ ] `fetch_btc_txs(address) -> list[dict]` met paginatie
- [ ] Rate-limit afhandeling
- [ ] Geen DB-toegang in dit bestand

**Test-scenarios:**
1. **Happy path:** bekend BTC-adres → lijst transacties.
2. **Edge case:** leeg adres → lege lijst.

### Blok 4.C — Bitcoin fetcher + UI

**Doel:** BTC-transacties geïmporteerd in `transactions` tabel met `source=bitcoin`.
**Aanbevolen model:** Sonnet.
**Branch:** feature/4-c-btc-fetch
**Wijzigt:** core/fetcher_btc.py (nieuw), pages/02_fetch.py.

**Acceptatiecriteria:**
- [ ] BTC adres-veld in pages/01_wallets.py
- [ ] Importeren-pagina toont BTC-resultaat apart
- [ ] BTC verschijnt op balansen + ledger pagina's

**Test-scenarios:**
1. **Happy path:** BTC-adres toevoegen → fetch → balans correct.
2. **Edge case:** xpub vs. los adres (alleen los adres in MVP).
3. **Regressie:** EVM-fetch onveranderd.

---

## Fase 5 — Beurzen (CSV-import)

**Doel:** CSV-export van centralized exchanges importeren als extra bron.
Volgorde: Bitvavo eerst (meest gebruikt), dan Kraken, dan Coinbase.

### Blok 5.A — Bitvavo CSV-importer

**Doel:** Bitvavo trade history CSV → `transactions` rows met source=bitvavo.
**Aanbevolen model:** Sonnet — duidelijk format, kunnen veel testen op echte CSV.
**Branch:** feature/5-a-bitvavo-import
**Wijzigt:** core/import_bitvavo.py (nieuw), pages/06_imports.py (nieuw).

**Acceptatiecriteria:**
- [ ] CSV-upload op nieuwe pagina
- [ ] BUY/SELL rijen → twee transactions (buy = receive asset, sell = send fiat) of equivalent
- [ ] Fees als aparte rows (analoog aan GAS_FEE)
- [ ] Idempotent: zelfde CSV opnieuw uploaden geeft 0 nieuwe

**Test-scenarios:**
1. **Happy path:** sample CSV met BUY+SELL → balansen correct.
2. **Edge case:** dubbele upload → dedup werkt.
3. **Edge case:** trade in obscuur token zonder coingecko mapping → geen crash, EUR-kolom "—".

### Blok 5.B — Kraken CSV-importer

**Doel:** Kraken ledgers.csv → transactions.
**Aanbevolen model:** Sonnet.
**Branch:** feature/5-b-kraken-import
**Wijzigt:** core/import_kraken.py (nieuw), pages/06_imports.py.

**Acceptatiecriteria:** vergelijkbaar met 5.A, aangepast aan Kraken-format.

**Test-scenarios:** vergelijkbaar.

### Blok 5.C — Coinbase CSV-importer

**Doel:** Coinbase transaction history CSV → transactions.
**Aanbevolen model:** Sonnet.
**Branch:** feature/5-c-coinbase-import
**Wijzigt:** core/import_coinbase.py (nieuw), pages/06_imports.py.

**Acceptatiecriteria:** vergelijkbaar.

---

## Fase 6 — Transactie-classificatie

**Doel:** TRANSFER_IN/OUT verfijnen tot BUY, SELL, SWAP_IN, SWAP_OUT, REWARD,
TRANSFER (interne wallet-transfer). Nodig voor correct werkelijk-rendement.

### Blok 6.A — DEX-router register + SWAP-detectie

**Doel:** Bekende DEX-routers per chain → transfers via deze contracten = SWAP.
**Aanbevolen model:** Opus — register-ontwerp + detectielogica.
**Branch:** feature/6-a-dex-routers
**Wijzigt:** core/models.py (DEX_ROUTERS dict), core/classify.py (nieuw).

**Acceptatiecriteria:**
- [ ] DEX_ROUTERS per chain (Uniswap V2/V3, 1inch, Sushi, Camelot)
- [ ] `classify_transaction(row) -> type` herschrijft type-veld
- [ ] Backfill-functie voor bestaande transactions

**Test-scenarios:**
1. **Happy path:** Uniswap swap → SWAP_OUT (token gegeven) + SWAP_IN (token ontvangen).
2. **Edge case:** transfer via niet-DEX contract → blijft TRANSFER_*.
3. **Regressie:** bridge-detectie (BRIDGE_OUT/IN) blijft werken.

### Blok 6.B — Linked_id voor swap-paren

**Doel:** Twee rijen van dezelfde swap koppelen via `linked_id`.
**Aanbevolen model:** Opus — datamodel-keuze.
**Branch:** feature/6-b-swap-pairs
**Wijzigt:** core/db.py (linked_id kolom), core/classify.py.

**Acceptatiecriteria:**
- [ ] Kolom `linked_id` (nullable) op transactions
- [ ] Heuristiek: zelfde tx_hash + verschillend type SWAP_IN/SWAP_OUT → koppelen
- [ ] Ledger-pagina toont gekoppelde swap als één regel met "→"

**Test-scenarios:**
1. **Happy path:** Uniswap swap → één gekoppelde regel op ledger.
2. **Edge case:** multi-hop swap (3+ tokens in één tx) → alle gekoppeld.

### Blok 6.C — REWARD-detectie

**Doel:** Inflows van bekende staking-contracten = REWARD (relevant voor belasting).
**Aanbevolen model:** Sonnet — uitbreiding op bestaande STAKED_TOKENS dict.
**Branch:** feature/6-c-rewards
**Wijzigt:** core/models.py (REWARD_CONTRACTS), core/classify.py.

**Acceptatiecriteria:**
- [ ] Inflow uit bekend staking-contract → REWARD ipv TRANSFER_IN
- [ ] Werkt voor xOPN-distributies, BEAM node ATH/WMC rewards

**Test-scenarios:**
1. **Happy path:** ATH-inflow uit BEAM staking-contract → REWARD.
2. **Edge case:** transfer van zelfde contract maar geen reward (theoretisch) → handmatige override mogelijk.

---

## Fase 7 — Delta reconcile-flow

**Doel:** Delta CSV als validatie-bron tegen alle andere imports. Alleen
unmatched Delta-transacties die jij goedkeurt belanden in de DB.

### Blok 7.A — Delta CSV parser

**Doel:** Delta export → genormaliseerde dict-lijst, zonder DB-toegang.
**Aanbevolen model:** Sonnet.
**Branch:** feature/7-a-delta-parser
**Wijzigt:** core/import_delta.py (nieuw).

**Acceptatiecriteria:**
- [ ] Parser leest Delta CSV-format
- [ ] Output: list van dicts met datum, type, asset, amount, source_label
- [ ] Geen DB-writes

**Test-scenarios:**
1. **Happy path:** sample CSV → correcte dict-lijst.
2. **Edge case:** lege CSV → lege lijst.

### Blok 7.B — Match-algoritme

**Doel:** Delta-rij matchen met bestaande DB-transacties (zelfde token,
vergelijkbaar bedrag, datum binnen tolerantie-window).
**Aanbevolen model:** Opus — datacorrelatie-algoritme, foutgevoelig.
**Branch:** feature/7-b-delta-match
**Wijzigt:** core/reconcile.py (nieuw).

**Acceptatiecriteria:**
- [ ] `match(delta_row, db_rows) -> match | None` met configurabele tolerantie
- [ ] Tolerantie default: ±24h, ±0,5% bedrag
- [ ] Test: 95%+ matches op een echte Delta-export
- [ ] Algoritme deterministisch en testbaar

**Test-scenarios:**
1. **Happy path:** Delta rij voor BTC-aankoop matcht Bitvavo-import.
2. **Edge case:** twee Delta-rijen kunnen op zelfde DB-rij matchen → kies dichtstbij.
3. **Edge case:** geen match → markeer als unmatched.

### Blok 7.C — Approval-UI voor unmatched

**Doel:** Pagina toont unmatched Delta-rijen → gebruiker kiest "accepteer als
losse rij" of "verwerp".
**Aanbevolen model:** Sonnet.
**Branch:** feature/7-c-delta-ui
**Wijzigt:** pages/07_delta.py (nieuw).

**Acceptatiecriteria:**
- [ ] Tabel met unmatched rijen + accept/reject knoppen
- [ ] Accepteer → transactions row met source=delta_manual + accept-flag
- [ ] Verwerp → niets in DB, rij gemarkeerd in import-log

**Test-scenarios:**
1. **Happy path:** import → 5 matched + 2 unmatched → 1 accepted, 1 rejected.
2. **Edge case:** dubbele upload → al-gematchte rijen niet opnieuw aangeboden.

---

## Fase 8 — Belastingrapport

**Doel:** Fiscaal correct jaaroverzicht: Box 3 forfait én werkelijk rendement,
incl. kostprijs-WMA en PDF-export.

### Blok 8.A — Box 3 forfait (waarde per 1 januari)

**Doel:** Pagina toont per jaar de waarde van het portfolio op 1 januari.
**Aanbevolen model:** Sonnet — bouwt op fase 3.C.
**Branch:** feature/8-a-box3-forfait
**Wijzigt:** core/tax.py (nieuw), pages/08_belasting.py (nieuw).

**Acceptatiecriteria:**
- [ ] Per jaar: totaal EUR per 1 jan
- [ ] Onderverdeling per token

**Test-scenarios:**
1. **Happy path:** 2024 → totaal klopt met handmatige check.
2. **Edge case:** jaar vóór eerste transactie → 0.

### Blok 8.B — Werkelijk rendement

**Doel:** Per token per jaar: open + close balans × prijs, plus alle buys/sells in
dat jaar gewogen. Op basis van fase 3.D + classificatie uit fase 6.
**Aanbevolen model:** Opus — fiscale correctheid kritiek.
**Branch:** feature/8-b-werkelijk-rendement
**Wijzigt:** core/tax.py, pages/08_belasting.py.

**Acceptatiecriteria:**
- [ ] Per token per jaar: open, close, in (BUY+REWARD), out (SELL), netto rendement EUR
- [ ] Aggregaat over hele portfolio
- [ ] Werkt over meerdere jaren

**Test-scenarios:**
1. **Happy path:** test-portfolio met bekende cijfers → output klopt.
2. **Edge case:** jaar met alleen swaps (geen fiat in/out) → rendement uit prijsbeweging.
3. **Edge case:** REWARD wordt als inkomst geteld, niet als TRANSFER.

### Blok 8.C — Kostprijs WMA (gerealiseerd resultaat)

**Doel:** Weighted moving average kostprijs per asset; bij elke verkoop het
gerealiseerde EUR-resultaat berekenen.
**Aanbevolen model:** Opus — algoritme + edge cases (FIFO vs WMA, partial fills).
**Branch:** feature/8-c-wma-kostprijs
**Wijzigt:** core/tax.py.

**Acceptatiecriteria:**
- [ ] WMA kostprijs per asset bijgehouden over tijd
- [ ] Gerealiseerd resultaat per verkoop = (verkoop_eur - wma_kostprijs × hoeveelheid)
- [ ] Aggregaat per jaar

**Test-scenarios:**
1. **Happy path:** 1 BTC kopen 30k, 1 BTC kopen 50k, 1 BTC verkopen 60k → WMA 40k → resultaat +20k.
2. **Edge case:** verkoop vóór aankoop (short, theoretisch) → gemarkeerd als ongeldig.
3. **Edge case:** REWARD als basis: kostprijs = EUR-waarde op moment van ontvangen.

### Blok 8.D — PDF export

**Doel:** Per jaar een PDF met alle relevante belastingdata.
**Aanbevolen model:** Sonnet — fpdf2 boilerplate.
**Branch:** feature/8-d-pdf
**Wijzigt:** core/pdf_export.py (nieuw), pages/08_belasting.py.

**Acceptatiecriteria:**
- [ ] PDF bevat: forfait-waarde 1 jan, werkelijk rendement, kostprijs-overzicht
- [ ] Download-knop op pagina
- [ ] Geschikt om als bijlage bij aangifte te bewaren

**Test-scenarios:**
1. **Happy path:** PDF opent in Preview, alle bedragen leesbaar.
2. **Edge case:** veel tokens → meerdere pagina's, geen overlapping.
