# Plan Fase 3 — EUR-prijslaag

Status: 3.1 t/m 3.10 afgerond en getest. Nagekomen 3.5-waarderingsstatus is afgerond en getest. Fase 3 is lokaal klaar voor expliciete review/merge.

Dit bestand is bedoeld als directe handoff voor een nieuwe chat. Fase 3 is lokaal
geïmplementeerd en getest; de volgende stap is expliciete review/merge of kickoff
van fase 4.

Canonieke locatie: `plans/plan-fase-3.md`.
Eventuele mirrors buiten de repo zijn alleen kopieën voor handoff, nooit de bron
van waarheid. Werk altijd vanuit de repo-versie.

## 1. Start Hier Voor Nieuwe Chat

Werk in repo:

```text
/Users/jeroen/Library/Mobile Documents/com~apple~CloudDocs/crypto-tracker
```

Copy-paste prompt:

```text
Controleer fase 3 voor review/merge. Gebruik plans/plan-fase-3.md als leidraad, run relevante tests/smoke checks, en voer geen merge uit zonder expliciete opdracht.
```

Gedrag voor de uitvoerende chat:

1. Lees `AGENTS.md`/`CLAUDE.md`, `CURRENT.md` en dit bestand.
2. Inspecteer de relevante code.
3. Voer alleen het huidige subblok uit.
4. Maak codewijzigingen in de repo.
5. Run de relevante tests.
6. Rapporteer gewijzigde bestanden en testresultaat.

Niet doen:

- Niet opnieuw de hele fase ontwerpen.
- Niet stoppen na "ik lees het plan".
- Geen merge uitvoeren zonder expliciete opdracht.

## 2. Subblokken

De hoofdblokken 3.A t/m 3.D blijven de review- en merge-eenheden. Voor uitvoering
werken we met kleinere subblokken.

| Subblok | Valt onder | Doel | Belangrijkste output |
|---|---|---|---|
| 3.0 | Kickoff | Scope vastzetten | Bouwplan + checklist/spec actueel |
| 3.1 | 3.A | Databasebasis | `price_cache`, `price_fetch_log`, index, env-vars |
| 3.2 | 3.A | Token-identiteit en mapping | `core/token_identity.py`, canonical assets, staking policies |
| 3.3 | 3.A | CoinGecko client + budgetbewaking | headers, retry, sleep, `calls_today()`, daily budget |
| 3.4 | 3.A | Prijs ophalen en cachen | `fetch_price`, `fetch_price_range`, `fetch_current_prices` |
| 3.5 | 3.B | Hoge-level EUR helpers | `core/prices.py`, `eur_value`, balance/ledger helpers |
| 3.6 | 3.B | Balansen-pagina met EUR | EUR-kolom, totaal, deels-onbekend indicator |
| 3.7 | 3.B | Transacties-pagina met EUR | EUR op tx-datum, bulk-prefetch, CSV-uitbreiding |
| 3.8 | 3.C | Jaaroverzicht snapshots | `balance_at`, `snapshot_for_year`, `pages/05_jaaroverzicht.py` |
| 3.9 | 3.D | Werkelijk rendement basis | `core/rendement.py`, `compute_year`, UI-sectie |
| 3.10 | Fase-review | End-to-end verificatie | tests, smoke test, budget-log, `/ultrareview` |

Werkvolgorde: eerst opslag en identiteit, dan prijs ophalen, dan EUR helpers,
daarna UI en rendement.

## 3. Subblok 3.1 — Databasebasis

Status: **afgerond op 2026-05-04**.

Doel: prijsopslag en API-call logging idempotent klaarzetten, zonder CoinGecko
client of UI.

Wijzigt:

- `core/db.py`
- `.env.example`
- gerichte schema-test, waarschijnlijk in `tests/test_db_migrations.py`

Acceptatiecriteria:

- [x] `price_cache` bestaat met `PRIMARY KEY (coingecko_id, date)`.
- [x] `price_cache` bevat `coingecko_id`, `date`, `eur`, `source`, `fetched_at`.
- [x] `price_fetch_log` bestaat met `PRIMARY KEY (date, source)`.
- [x] `price_fetch_log` bevat `date`, `source`, `count`.
- [x] `idx_price_cache_date` bestaat.
- [x] `init_db()` maakt tabellen/index idempotent aan op verse DB.
- [x] Bestaande DB-migraties blijven groen.
- [x] `.env.example` bevat `COINGECKO_API_KEY=`.
- [x] `.env.example` bevat `COINGECKO_DAILY_CALL_BUDGET=300`.

Uitgevoerd:

- `core/db.py`: `price_cache`, `price_fetch_log`, `idx_price_cache_date`.
- `.env.example`: CoinGecko env-vars.
- `tests/test_db_migrations.py`: idempotente schema-test.
- Tests: `uv run python -m unittest tests.test_db_migrations` en `uv run python -m unittest discover -s tests`.

Niet doen in 3.1:

- Geen `core/coingecko.py` bouwen.
- Geen `COINGECKO_IDS` mapping toevoegen.
- Geen `core/prices.py` toevoegen.
- Geen UI aanpassen.
- Geen echte API-calls doen.

Aanpak:

1. Inspecteer `core/db.py`, `.env.example` en bestaande DB-tests.
2. Voeg `price_cache` en `price_fetch_log` toe aan `SCHEMA_SQL`.
3. Voeg `idx_price_cache_date` toe aan `INDICES_SQL`.
4. Voeg zo nodig migratie/idempotentie-logica toe voor bestaande DB's.
5. Voeg de CoinGecko env-vars toe aan `.env.example`.
6. Voeg of update tests die aantonen dat tabellen/index bestaan na `init_db()`.
7. Run minimaal:

```bash
uv run python -m unittest tests.test_db_migrations
```

Bij bredere impact ook:

```bash
uv run python -m unittest discover -s tests
```

## 4. Subblok 3.2 — Token-identiteit en mapping

Status: **afgerond op 2026-05-04**.

Doel: voorkomen dat verkeerde tokens een prijs krijgen door symbol-collisions,
en multichain/wrapper-semantiek expliciet buiten de prijslaag vastleggen.

Acceptatiecriteria:

- [x] `core/token_identity.py` gebruikt `(chain, contract_address | None) -> canonical_asset -> coingecko_id`.
- [x] Native tokens gebruiken `contract_address = None`.
- [x] `coingecko_id_for()` resolveert known tokens.
- [x] ARB op Arbitrum, BEAM/WBEAM en ATH op Ethereum/Arbitrum mappen via contract naar canonical asset.
- [x] xOPN/stPEAR zijn staking-wrapperrelaties met expliciete stake-event pricing policy, geen directe prijsredirect.
- [x] Onbekende/scam/LP tokens geven `None`.
- [x] Geen symbol-only fallback die scam-USDC/ARB/BEAM/ATH/OPN/PEAR echte prijzen kan geven.

Uitgevoerd:

- `core/token_identity.py`: centrale token-identiteit, canonical assets, CoinGecko-id mapping en staking-wrapper policies.
- `core/models.py`: compatibility exports voor bestaande imports.
- `core/prices.py`: wrappers worden niet direct geprijsd als gewone tokens.
- `core/token_review.py`: bekende canonical contracts en fake-wrapper-contracten worden bewaakt.
- `tests/test_models.py`, `tests/test_prices.py`, `tests/test_token_review.py`: native mapping, contract mapping, ARB/BEAM/ATH aliases, staking policies, fake-token scenario's.
- Tests: `uv run python -m unittest tests.test_models` en `uv run python -m unittest discover -s tests`.

## 5. Subblok 3.3 — CoinGecko Client + Budgetbewaking

Status: **afgerond op 2026-05-04**.

Doel: veilige API-laag binnen free-tier limieten.

Acceptatiecriteria:

- [x] Headers gebruiken `COINGECKO_API_KEY` als die bestaat.
- [x] Retry/backoff bij 429 en tijdelijke HTTP-fouten.
- [x] Minimaal 2,5s tussen sequential API-calls.
- [x] `calls_today()` leest uit `price_fetch_log`.
- [x] Elke echte API-call verhoogt `price_fetch_log`.
- [x] Bij overschrijding van `COINGECKO_DAILY_CALL_BUDGET` cache-only gedrag.

Uitgevoerd:

- `core/coingecko.py`: `headers()`, `calls_today()`, `budget_remaining()`, `request_json()`, retry/backoff, interval-throttle, call logging.
- `tests/test_coingecko.py`: headers, budgetlog, budget guard, retry/backoff, transport retry, interval-throttle.
- Tests: `uv run python -m unittest tests.test_coingecko` en `uv run python -m unittest discover -s tests`.

## 6. Subblok 3.4 — Prijs Ophalen En Cachen

Status: **afgerond op 2026-05-04**.

Doel: prijsfuncties zonder UI.

Acceptatiecriteria:

- [x] `fetch_price(coingecko_id, date)` is cache-first.
- [x] `fetch_price_range(coingecko_id, start, end)` gebruikt bulk `market_chart`.
- [x] `fetch_current_prices(coingecko_ids)` gebruikt `/simple/price`.
- [x] Tweede call voor dezelfde `(coingecko_id, date)` doet geen HTTP-call.
- [x] Bulk range schrijft dagelijkse rijen naar `price_cache`.

Uitgevoerd:

- `core/coingecko.py`: `fetch_price`, `fetch_price_range`, `fetch_current_prices`, `price_cache` helpers.
- Current `/simple/price` cache gebruikt aparte source zodat oude intraday-prijzen later niet als historische close worden hergebruikt.
- `tests/test_coingecko.py`: cache-first, no second HTTP call, range bulk write, no wrong-date fallback, current-price cache-only.
- Tests: `uv run python -m unittest tests.test_coingecko` en `uv run python -m unittest discover -s tests`.

## 7. Subblok 3.5 — Hoge-level EUR Helpers

Status: **afgerond op 2026-05-04**.

Doel: prijsclient bruikbaar maken voor balansen en ledger, nog zonder UI.

Acceptatiecriteria:

- [x] `core/prices.py` bestaat.
- [x] `eur_value(coingecko_id, amount, date)` geeft Decimal EUR of `None`.
- [x] Helpers voor balance/ledger kunnen later bulkprijzen gebruiken.
- [x] Wrappers blijven via expliciete staking-policy voorbereid, zonder naïeve directe prijs.

Uitgevoerd:

- `core/prices.py`: `eur_value`, `eur_balances_today`, `eur_transactions`, `has_unknown_eur`.
- `tests/test_prices.py`: Decimal-vermenigvuldiging, onbekende/missende prijzen, bulk current prices, geen directe wrapper-prijs, ledger prefetch per token/jaar.
- Tests: `uv run python -m unittest tests.test_prices` en `uv run python -m unittest discover -s tests`.

## 8. Subblok 3.6 — Balansen-Pagina Met EUR

Status: **afgerond op 2026-05-04**.

Doel: EUR-kolom en totaalwaarde tonen op de balansen-pagina.

Acceptatiecriteria:

- [x] Balansen-pagina toont kolom "Waarde (EUR)".
- [x] Balansen-pagina toont totale EUR-waarde.
- [x] Totaal markeert "(deels onbekend)" als één of meer EUR-cellen ontbreken.
- [x] Page gebruikt `core.prices.eur_balances_today()`; geen prijslogica in UI.
- [x] Na afronding draait Streamlit en is de lokale URL gerapporteerd.

Uitgevoerd:

- `pages/03_balances.py`: contract-aware balances, EUR-kolom, totaalwaarde, deels-onbekend indicator.
- `core/prices.py`: tijdelijke CoinGecko-fouten geven ontbrekende EUR-waarden in plaats van een crash.
- `tests/test_prices.py`: extra foutpad voor current-prices.
- Tests: `uv run python -m unittest tests.test_prices`, `uv run python -m py_compile pages/03_balances.py core/prices.py`, `uv run python -m unittest discover -s tests`.
- App gestart op `http://localhost:8510`.

## 9. Subblok 3.7 — Transacties-Pagina Met EUR

Status: **afgerond op 2026-05-04**.

Doel: EUR op transactiedatum tonen op de Transacties-pagina en meenemen in CSV-export.

Acceptatiecriteria:

- [x] Transacties-pagina toont kolom "EUR (op tx-datum)".
- [x] Transacties-pagina gebruikt `core.prices.eur_transactions()`.
- [x] CSV-export bevat EUR-kolom.
- [x] Geen N+1 calls; prijzen blijven gebundeld per `(coingecko_id, jaar)`.

Uitgevoerd:

- `pages/04_transacties.py`: EUR-kolom voor boekingsregels en gegroepeerde transacties, CSV-EUR-kolommen.
- `pages/03_balances.py`: crashfix voor contract-aware bridge-expander sleutel.
- Tests: `uv run python -m py_compile pages/03_balances.py pages/04_transacties.py core/prices.py`, `uv run python -m unittest tests.test_prices tests.test_ledger`, `uv run python -m unittest discover -s tests`.
- Let op: `pages/04_transacties.py` was al >400 regels vóór dit subblok; later splitten als er substantieel verder aan gewerkt wordt.

## 10. Subblok 3.8 — Jaaroverzicht Snapshots

Status: **afgerond op 2026-05-04**.

Doel: portfolio snapshot op 1 januari en 31 december per jaar.

Acceptatiecriteria:

- [x] `core.prices.py` bevat `balance_at(date)` en `snapshot_for_year(year)`.
- [x] Pagina `pages/05_jaaroverzicht.py` met dropdown jaar.
- [x] Jaarlijst loopt van eerste tx-jaar tot huidig jaar.
- [x] Lazy per jaar: alleen geselecteerd jaar raakt de API.
- [x] Bulk-fetch: één `market_chart` call per token per jaar.

Uitgevoerd:

- `core/prices.py`: `available_years`, `balance_at`, `snapshot_price_ids`, `snapshot_for_year`.
- `pages/05_jaaroverzicht.py`: jaarselectie, budgetmelding, laadknop, 1-1/31-12 tabel en totalen.
- `tests/test_prices.py`: balance-at, snapshot, call-estimate tests.
- Tests: `uv run python -m unittest tests.test_prices`, `uv run python -m py_compile core/prices.py pages/05_jaaroverzicht.py`, `uv run python -m unittest discover -s tests`.

## 11. Subblok 3.9 — Werkelijk Rendement Basis

Status: **afgerond op 2026-05-05**.

Doel: voorlopige werkelijk-rendement berekening tonen op het jaaroverzicht.

Acceptatiecriteria:

- [x] Module `core/rendement.py` met `compute_year(year) -> list[dict]`.
- [x] Per `(wallet, chain, token)`: open_eur, close_eur, in_eur, out_eur, gas_eur, netto_eur.
- [x] Netto formule: `(close_eur - open_eur) - (in_eur - out_eur)`.
- [x] GAS_FEE is info-kolom en telt niet mee in de formule.
- [x] Jaaroverzicht-pagina toont sectie "Werkelijk rendement".

Uitgevoerd:

- `core/prices.py`: publieke `transaction_price_ids()` helper voor contract-aware budgetschatting.
- `core/rendement.py`: basisberekening per wallet/chain/token-contract met snapshot-EUR, in/out-EUR, gas-EUR, netto-EUR en contract-aware prijs-id schatting.
- `pages/05_jaaroverzicht.py`: sectie "Werkelijk rendement", aggregaat-totaal, status, budgetschatting inclusief rendement-transacties en disclaimer dat classificatie in fase 6/8 wordt verfijnd.
- `tests/test_rendement.py`: formule, gas-informatiekolom, token gestart/verkocht binnen hetzelfde jaar, missende prijs, saldo-zonder-jaartransacties en fake-token prijs-id regressie.
- Tests: `uv run python -m unittest tests.test_rendement`, `uv run python -m py_compile core/rendement.py pages/05_jaaroverzicht.py`, `uv run python -m unittest discover -s tests`.

## 12. Nagekomen 3.5 — Handmatige Waardering

Status: **afgerond op 2026-05-04**.

Doel: tokens zonder betrouwbare marktwaarde handmatig vanaf een datum op nul
kunnen waarderen, zonder fiscale conclusie te trekken.

Uitgevoerd:

- `core/token_valuation.py`: `active`, `unknown`, `manual_zero`, `worthless`.
- `core/db.py`: waarderingskolommen op `token_review`.
- `core/prices.py`: `manual_zero`/`worthless` geeft vanaf ingangsdatum EUR 0;
  onbekende marktprijs blijft `—`.
- `pages/02_fetch.py`: editor "Handmatige waardering".
- `pages/03_balances.py`, `pages/04_transacties.py`, `pages/05_jaaroverzicht.py`:
  handmatige nulwaardering zichtbaar in EUR-cellen/tabel.
- Tests: `uv run python -m unittest discover -s tests` groen.

## 13. Subblok 3.10 — Fase-Review

Status: **afgerond op 2026-05-05**.

- **3.5:** `core/prices.py` met `eur_value`, `eur_balances_today`, `eur_transactions`.
- **3.6:** balansen-pagina toont EUR-kolom en totaal.
- **3.7:** transacties-pagina en CSV-export krijgen EUR op transactiedatum.
- **3.8:** jaaroverzicht met 1 januari en 31 december snapshots.
- **Nagekomen 3.5:** handmatige nulwaardering vanaf datum zonder fiscale conclusie.
- **3.9:** werkelijk-rendement basis met `core/rendement.py`.
- **3.10:** fase-review, tests, compile/smoke checks en budget/cache-checks.

Uitgevoerd:

- Volledige test-suite: `uv run python -m unittest discover -s tests` — 103 tests groen.
- Compile-check: `uv run python -m py_compile ...` voor fase-3 core/pages/tests groen.
- Review-fix in `core.prices.snapshot_for_year()`: lege peildatumkant wordt nu EUR 0 in plaats van `—`/deels-onbekend.
- Regressietests toegevoegd voor volledig verkocht vóór 31-12 en pas gekocht na 1-1.
- Code-checks: geen symbol fallback in prijslaag; fake-token tests bewaken ARB/BEAM/ATH/OPN/PEAR; staking wrappers blijven zonder directe prijsredirect.
- App-processen luisteren lokaal volgens `lsof`; `curl` naar localhost was vanuit de sandbox niet bruikbaar, dus geen browser-output of echte DB-data gedumpt.

## 14. Ontwerpregels Fase 3

- Mapping gebeurt via `core/token_identity.py`: `(chain, contract_address | None) -> canonical_asset -> coingecko_id`, niet via ticker.
- `price_cache` gebruikt `PRIMARY KEY (coingecko_id, date)`.
- CoinGecko is primair.
- CoinMarketCap is alleen fallback voor huidige prijzen/id-resolutie, niet historisch.
- Default prijsophaalpad is bulk/cache-first.
- API-budget wordt bewaakt met `price_fetch_log` en `COINGECKO_DAILY_CALL_BUDGET`.
- Onbekende tokens tonen later `—` in EUR-cellen, nooit een gegokte prijs.
- Staking wrappers zoals xOPN/stPEAR hebben geen directe prijsredirect; stake/unstake-eventlogica moet de ingelegde underlying en latere yield reconstrueren.
