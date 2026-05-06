# Review Fase 1 + 2 — Crypto Portfolio Tracker

**Datum:** 2026-05-05
**Branch:** `feature/3-a-prices-core` (review draait op de gemergde fase 1 + fase 2 code in deze worktree)
**Reviewer:** Claude Opus 4.7 — core-laag, schema, fiscale correctheid, pages, walkthrough
**Plan:** `~/.claude/plans/ik-wil-een-code-optimized-hummingbird.md`

---

## Status van dit document

- [x] Sectie 1 — Samenvatting (Opus afgerond, incl. pages-bevindingen)
- [x] Sectie 2 — Bevindingen `core/` (Opus afgerond)
- [x] Sectie 3 — Test-gaps (Opus afgerond)
- [x] Sectie 4 — Bevindingen `pages/` (Opus afgerond)
- [x] Sectie 5 — Code-walkthrough (Opus; UI-visueel: syntax + imports groen, 103 tests groen)
- [x] Sectie 6 — Doorwerking naar fase 4 (Opus afgerond)

---

## 1. Samenvatting

### Top-3 risico's (definitief, na core- en pages-review)

1. **`to_decimal()` silent fallback naar `Decimal("0")`** in `core/models.py:125-130` —
   wordt gebruikt in `core/parsers.py` voor `value` / `gasUsed` / `gasPrice`. Een
   parse-fout door een onverwachte API-format leidt tot een verloren transactie
   of een gas-fee van 0, zonder log of warning. Voor fiscale correctheid een
   Major-risico.

2. **Geen tests voor `core/balance_check.py`, `core/fetcher.py`-dedup, `core/wrap_reconcile.py`** —
   precies de plekken waar fase 1 lessen 1-3 zijn vastgelegd, hebben geen
   regressie-net. Een schemawijziging of refactor in fase 4 kan stil breken.

3. **Architectuurdrift: 5 files boven CLAUDE.md's 400-regel limiet + embedded SQL in 4 pages** —
   `core/token_review.py` (1442), `pages/04_transacties.py` (604 + 5 SQL-helpers),
   `pages/02_fetch.py` (518 + 3 SQL-helpers), `pages/01_wallets.py` (3 SQL-helpers),
   `pages/03_balances.py` (verborgen SQL in BEAM-knop), `core/fetcher.py` (442),
   `core/api.py` (426). Niet acuut foutgevoelig, wel onderhoudslast en
   architectuurschuld voor fase 4+.

### Top-3 sterke punten

1. **Les 1 (dedup-key) volledig doorgevoerd** — schema (`UNIQUE (tx_hash, wallet_id, source)` op `core/db.py:40`),
   migratie (`_migrate_tx_dedup_constraint` op `core/db.py:184` met heldere root-cause-docstring),
   en in-memory dedup (`core/fetcher.py:113-123` + `:300`). Zelden zie je een geleerde les zo schoon op alle drie de niveaus.

2. **Les 2 + 3 (drie endpoints + GAS_FEE) correct** — `core/fetcher.py:318-365`
   gebruikt tokentx + txlist + txlistinternal met onafhankelijke cursors;
   `core/parsers.py:126-144` produceert GAS_FEE-rij voor sender ook bij
   `isError=1` met formule `(gas_used * gas_price) / 10^18`. Per-endpoint
   cursor-update is conservatief (`fetcher.py:377-382` skipt geërrorde endpoints).

3. **Contract-aware token-key end-to-end** — `core/token_review.py:196-218`
   biedt `token_key`/`token_key_sql`/`token_review_join_condition` als één
   waarheidsbron, met `_CANONICAL_TICKER_CONTRACTS`-register
   (`token_review.py:59-93`) voor ticker-impersonatie. Migratie
   `_migrate_token_review_contract_keys` (`db.py:286`) bouwt oude asset-keyed
   rijen schoon om naar contract-keys.

---

## 2. Bevindingen `core/`

Categorieën: **Blocker** (release-stop) / **Major** (vooraf fixen aan fase 3) /
**Minor** (planbaar voor latere fase) / **Nit** (cosmetisch).

### Blocker

Geen blockers gevonden. Fase 1+2 zijn fundamenteel solide.

### Major

**M1 — `to_decimal()` silent fallback naar 0** &middot; `core/models.py:125-130`
- Parse-fout op gehele/grote integer-strings (bijv. ooit `null`, `""`,
  hex-format) → `Decimal("0")` zonder log.
- Gebruikt in `parsers.py:100, 108, 127, 128, 154, 171` voor on-chain
  geldwaarden.
- Risico: stille tx-drop (value=0 → geen rij gegenereerd) of gas-fee=0
  (geen GAS_FEE-rij). Audit-onzichtbaar.
- **Voorstel:** voeg `to_decimal_strict()` toe die `InvalidOperation`/`ValueError`
  raiset, en gebruik die in `parsers.py`. Of log een warning in `to_decimal()`
  bij fallback. Behoud `to_decimal()` voor display-only paden.

**M2 — Geen tests voor `core/balance_check.py`** &middot; complete file
- `verify_balances()` heeft veel branching: native vs. ERC-20, decimals
  known/unknown, error-paden, renamed-native (ETH-0x...). Allemaal
  ongetest.
- Dit is de safety-feature waarmee dataverlies à la "ETH 96" wordt opgespoord.
- **Voorstel:** test-file `tests/test_balance_check.py` met monkeypatched
  `api.fetch_native_balance` / `fetch_token_balance` en een seeded
  `transactions` + `token_meta` tabel.

**M3 — Geen tests voor fetcher-dedup-logica** &middot; `core/fetcher.py:113-310`
- Cross-wallet dedup, cross-source dedup, en de `_dup{N}` suffix-logica zijn
  niet expliciet getest. Indirect gedekt via `tests/test_ledger_backfill.py`
  (suffix-handling) maar niet de dedup-key zelf.
- **Voorstel:** `tests/test_fetcher_dedup.py` met seeded transactions en
  fixture-API rows die collisies forceren.

**M4 — `_upsert_token_review` opent een DB-connectie per buffer-rij** &middot; `core/fetcher.py:372-375`
- N rijen → N `sqlite3.connect()` opens. Bij eerste fetch met 5000+ rijen
  voelbaar traag.
- **Voorstel:** dedup tot `unique (asset, contract)` set vóór de loop,
  daarna één connectie + transaction.

**M5 — Per-rij INSERT + `SELECT changes()` in `_insert_rows`** &middot; `core/fetcher.py:138-159`
- 2 round-trips per rij voor de "did insert?" telling.
- **Voorstel:** `executemany()` + count via `cur.rowcount` of pre-check
  van bestaande hashes.

**M6 — `core/token_review.py` is 1442 regels** &middot; CLAUDE.md sectie 6
- 3,5× over de 400-regel limiet.
- **Voorstel-split:**
  - `core/token_review/scam.py` — `_SCAM_RE`, `is_scam`, `_LEGIT_OVERRIDE`,
    `_CANONICAL_TICKER_CONTRACTS`
  - `core/token_review/classify.py` — `classify_token`,
    `_ticker_impersonation_reason`, `is_suspicious_by_metadata`
  - `core/token_review/intake.py` — `token_intake_guidance`,
    `token_intake_sort_key`, bucket-constants
  - `core/token_review/enrich.py` — `enrich_public_sources`,
    `_refresh_coingecko_*`, `_refresh_goplus_*`,
    `_refresh_coinmarketcap_*`, `enrich_tokens`
  - `core/token_review/actions.py` — `set_token_accepted`,
    `accept_recommended_tokens`, `auto_reject_scams`,
    `reclassify_all_token_reviews`, `sync_staking_wrappers`
- Splitsen pas in eigen blok; deze review documenteert alleen.

**M7 — `core/api.py` (426 regels) bevat 4 verschillende externe API's**
- Etherscan + Routescan + CoinGecko + GoPlus + CoinMarketCap in één file.
- Tegen CLAUDE.md sectie 6: "Nieuwe externe API's krijgen hun eigen HTTP-laag".
- **Voorstel-split:**
  - `core/api_etherscan.py` — etherscan/routescan + retry/paginate
  - `core/api_public_evidence.py` — coingecko/goplus/cmc voor token-review
- Fase 3-werk introduceert al `core/coingecko.py` voor het price-cache pad
  (een aparte CoinGecko-laag voor prijzen, los van token-review-evidence).
  Bij splitsen meeplannen.

### Minor

**m1 — `init_db()` triggert `reclassify_all_token_reviews()` bij elke start** &middot; `core/db.py:379-380`
- Side-effect: trage app-startup en alle tests die `init_db()` aanroepen
  draaien deze functie ook.
- **Voorstel:** opt-in flag of expliciete trigger vanuit `app.py` na boot.

**m2 — `core/db.py:_migrate_token_review_contract_keys` reset `accepted=0`** &middot; `db.py:332`
- Pre-migratie tokens worden allemaal als provisional behandeld; gebruiker
  moet alle tokens opnieuw accepteren.
- Gedocumenteerd in docstring (`db.py:288-292`), maar verifieer dat
  `reclassify_all_token_reviews()` daadwerkelijk auto-accept doet voor
  veilige tokens — anders verliest de gebruiker alle hand-accepts.
- **Voorstel:** test deze migratie op een seeded oude DB.

**m3 — `_dup{N}` suffix bij multi-Transfer in tokentx** &middot; `core/fetcher.py:322-332`
- Voor Etherscan-rijen zonder `logIndex` wordt op volgorde gerekend. Bij
  re-orgs of API-bug die de volgorde wisselt, kunnen "geest"-rijen
  achterblijven.
- **Voorstel:** als Etherscan ooit `logIndex` gaat exposen, gebruik die.
  Voor nu acceptabel maar latent risico.

**m4 — Silent drop in `_parse_tokentx_row` bij decimals-parse-fout** &middot; `core/parsers.py:47-51`
- `return None` zonder log bij `InvalidOperation/ValueError` op `value` of
  `tokenDecimal`.
- **Voorstel:** log warning of accumuleer in `FetchResult` als
  `parse_errors`.

**m5 — N+1 query in `_accepted_balances`** &middot; `core/balance_check.py:82-91`
- Voor N tokens, N+1 SELECT-queries voor exact Decimal-sum.
- **Voorstel:** één query met `GROUP_CONCAT(amount)` of `JSON_GROUP_ARRAY`
  + Python-side parse.

**m6 — `rough_sum` in SELECT maar nergens gebruikt** &middot; `core/balance_check.py:66`
- Dode kolom in de SELECT-clause.
- **Voorstel:** weghalen, alleen `GROUP BY` op de keys.

**m7 — Bare `except Exception: return None`** &middot; `core/staking.py:33-34, 77-78`
- Bug in `STAKED_TOKENS` of API → silent None, gebruiker ziet "geen
  staking rate" zonder spoor.
- **Voorstel:** log de exception (geen raise; UI moet stabiel blijven).

**m8 — `BEAM_STAKING_CONTRACT` hardcoded in `core/staking.py:48`**
- Hoort in `core/models.py` bij andere contract-registers, of in een
  `STAKING_CONTRACTS`-mapping naar chain.
- **Voorstel:** verplaats naar `core/models.py`.

**m9 — `fetch_beam_staking_balance` haalt hele txlist elke aanroep** &middot; `core/staking.py:58, 68`
- Geen cache. Pages-knop maakt het lazy ✓ maar bij meerdere wallets met
  BEAM-staking nog wel duur.
- **Voorstel later:** cache balance in memory of in een aparte
  `staking_balance_cache` tabel.

**m10 — `_single_call` dupliceert retry-logica van `_request_with_retry`** &middot; `core/api.py:354-381` vs `:140-155`
- DRY-overtreding.
- **Voorstel:** extract `_retry_loop(fn, classify)` helper.

**m11 — `load_env()` op import-time in `core/api.py:33`**
- Side-effect bij elke import; tests die alleen helper-functies willen
  importeren krijgen toch een env-load.
- **Voorstel:** verplaats naar functie-niveau of accepteer expliciet.

**m12 — `int(_single_call(...))` zonder guard** &middot; `core/api.py:397, 414, 426`
- Bij onverwachte non-numerieke response throw `ValueError`.
- **Voorstel:** parse + log + raise eigen `EtherscanError("non-numeric balance")`.

**m13 — `token_key()` Python doet `.strip()`, `token_key_sql()` niet** &middot; `core/token_review.py:198` vs `:207-209`
- Subtiele inconsistentie. Theoretisch want Etherscan strip altijd, maar
  bug-magnet.
- **Voorstel:** SQL ook `lower(trim(contract_address))`.

**m14 — Scam-regex `[À-ÖØ-ö]{2,}`** &middot; `core/token_review.py:38`
- Latijnse diakritieken-pattern triggert op Franse/Duitse/Spaanse legitieme
  tokens.
- **Voorstel:** monitoring; uitbreiden van `_LEGIT_OVERRIDE` of regex
  verfijnen.

**m15 — Native-symbol collision via `contract[:6]`** &middot; `core/parsers.py:67-68`
- 6 hex chars (3 bytes) = 16M combinaties. Theoretische collision tussen
  twee "ETH"-genaamde scam-tokens.
- **Voorstel:** `contract[:10]` of volledige contract — niet kritiek.

### Nit

**n1 — Geen `schema_version` tabel** &middot; `core/db.py`
- Migratie-state via `PRAGMA table_info` + `sqlite_master`. Werkt, maar
  bij partial migratie risico op inconsistente state. Acceptabel voor
  lokaal + backup-strategie.

**n2 — `format_token` Dutch locale via X-replace hack** &middot; `core/models.py:144-146`
- `formatted.replace(",", "X").replace(".", ",").replace("X", ".")`. Werkt,
  maar `locale.format_string` zou cleaner zijn.

**n3 — `int(blockNumber)` zonder try/except** &middot; `core/parsers.py:74, 93, 179`
- Crash bij onverwachte API-output i.p.v. graceful skip.

**n4 — `datetime.now()` zonder UTC in `core/backup.py:15`**
- DST-overgang kan twee backups dezelfde timestamp geven.

**n5 — `time.sleep(0.15)` na elke wallet/chain in `core/fetcher.py:427`**
- Willekeurig nummer; rate-limit zit al in `api.py` (`INTER_PAGE_DELAY = 0.25s`).

**n6 — Hardcoded DB_PATH zonder env-override** &middot; `core/db.py:6`
- Voor tests is monkeypatch genoeg; voor productie OK. Cosmetisch.

---

## 3. Test-gaps

| Onderwerp | Module | Status | Kritikaliteit |
|---|---|---|---|
| Schema-migraties | `core/db.py` | Gedekt: `tests/test_db_migrations.py` | — |
| Token-classificatie + scam-filter | `core/token_review.py` | Goed gedekt: `tests/test_token_review.py` (28 tests) | — |
| Fetcher dedup (cross-wallet, cross-source) | `core/fetcher.py:113-310` | **Geen** directe tests | Major |
| Drie endpoints integratietest | `core/fetcher.py` | Geen end-to-end test | Minor |
| `core/balance_check.py` | complete file | **Geen tests** | Major |
| `core/wrap_reconcile.py` | complete file | **Geen tests** | Major |
| `core/staking.py` (raw `fetch_beam_staking_balance`) | `core/staking.py` | Indirect via `tests/test_balances.py` | Minor |
| `core/backup.py` | complete file | **Geen tests** | Minor |
| Decimal correctheid | doorheen `core/` | Indirect via prices/balances tests | — |
| `to_decimal()` strict variant (zie M1) | `core/models.py` | n.v.t. — feature ontbreekt | Major (M1) |

**Voorstel voor fase 3-aansluitend test-blok**: één PR die `tests/test_fetcher_dedup.py`,
`tests/test_balance_check.py`, `tests/test_wrap_reconcile.py`, `tests/test_backup.py`
toevoegt. Niet binnen deze review.

---

## 4. Bevindingen `pages/`

Categorieën consistent met sectie 2. Pages gereviewed: `app.py`, `01_wallets.py`,
`02_fetch.py`, `03_balances.py`, `04_transacties.py`. Alle bestanden syntax-fout-vrij
en alle imports resolven foutloos (geverifieerd via `py_compile` + import-check).

### Major

**P1 — Embedded SQL in `pages/01_wallets.py`** &middot; `pages/01_wallets.py:16-52`
- `_get_wallets()` (JOIN met `wallet_chain_state`), `_add_wallet()` (INSERT),
  `_delete_wallet()` (DELETE) — drie raw SQL-functies direct in een page.
- CLAUDE.md §6: "Pages bevatten geen business logic; ze roepen `core.*` aan en renderen."
- `_delete_wallet()` bevat ook business logic: roept `create_backup()` vóór de delete aan.
- **Voorstel:** extraheer naar `core/wallets.py` met functies `get_wallets()`,
  `add_wallet()`, `delete_wallet()`. Pages importeren alleen `core.wallets`.

**P2 — Embedded SQL in `pages/02_fetch.py`** &middot; `pages/02_fetch.py:35-63`
- `_get_wallets()`, `_inbox_count()` (COUNT(*) FROM transactions),
  `_reset_inbox()` (DELETE FROM transactions + wallet_chain_state + token_review).
- `_reset_inbox()` bevat pure business logic: orkestreert een destructieve
  multi-tabel reset. Dit hoort in `core/fetcher.py` of `core/db.py`.
- **Voorstel:** `core/wallets.py` voor wallets-CRUD; `core/fetcher.py` voor reset-logica.

**P3 — Embedded SQL in `pages/03_balances.py` (BEAM-knop)** &middot; `pages/03_balances.py:366-373`
- Verborgen architectuurschending: inside een button-handler staan lazy imports
  van `get_connection` + een raw SQL `SELECT id, name, address FROM wallets`.
- **Voorstel:** gebruik het al beschikbare `core.balances.get_wallets()` dat
  op dezelfde page al geïmporteerd is (`pages/03_balances.py:6`).

**P4 — Embedded SQL in `pages/04_transacties.py`** &middot; `pages/04_transacties.py:79-225`
- Vijf helper-functies bevatten alle embedded SQL:
  `_get_wallets()`, `_get_chains()` (JOIN token_review), `_get_years()`
  (substr-trick), `_get_assets()` (optionele filters), `_get_transactions()`
  (60-regel JOIN-query met GROUP BY).
- `_get_transactions()` bevat de meest complexe query in het hele project en
  hoort thuis in `core/ledger.py` als `get_ledger_transactions()`.
- **Voorstel:** extraheer alle vijf naar `core/ledger.py` of `core/transactions.py`.

**P5 — `pages/02_fetch.py` is 518 regels** &middot; CLAUDE.md §6
- De token-review UI-sectie (regels 142-517) is bijna een eigen applicatie.
- **Voorstel-split:** extraheer de expander-logica voor INTAKE_REVIEW/INTAKE_NOISE
  naar een page-helper of splits de pagina in "Ophalen" + "Token review".

**P6 — `pages/04_transacties.py` is 604 regels** &middot; CLAUDE.md §6
- **Voorstel-split:**
  - Extraheer `_get_*` functies naar `core/ledger.py`.
  - Groepeer de vier DataFrame-builders
    (`_table_df`, `_grouped_table_df`, `_csv_df`, `_grouped_csv_df`) in een
    page-helper module.

### Minor

**p1 — BEAM staking niet in portfolio-totaal** &middot; `pages/03_balances.py:191, 358-389`
- `total_eur` (regel 191) telt alleen `display_balances`; de BEAM-staking-sectie
  (regels 358-389) is een volledig apart blok dat buiten `display_balances` valt.
- De header-metric "Waarde EUR" (regel 198) is dus exclusief gestaked BEAM,
  zonder expliciete disclaimer.
- **Voorstel:** voeg `"(excl. staking)"` toe als `delta`-argument aan de
  EUR-metric als de BEAM-sectie ooit saldo toont. Of tel het mee als de
  staking-balance al geladen is.

**p2 — Asset-filter Python-side in transacties** &middot; `pages/04_transacties.py:520`
- `_get_transactions()` haalt alle transacties op (geen asset-parameter);
  regel 520 filtert daarna in Python: `[row for row in all_rows if ... row["asset"] == selected_asset]`.
- Bij wallets met 10.000+ transacties worden alles in geheugen geladen vóór filtering.
- **Voorstel:** voeg `asset: str | None` parameter toe aan de query.

**p3 — Dubbele metric-label "Boekingsregels" in Boekingsregels-view** &middot; `pages/04_transacties.py:532-534`
- `c1.metric(view_label, visible_count)` + `c2.metric("Boekingsregels", len(raw_rows))`
  tonen bij view="Boekingsregels" beide dezelfde tekst én waarde.
- **Voorstel:** c2 toont bij Boekingsregels-view het aantal unieke tx_hashes
  ("Transacties: M") voor extra context.

**p4 — `sync_staking_wrappers()` bij elke render** &middot; `pages/03_balances.py:18`
- Side-effect DB-aanroep bij elke page-render, ook als niets veranderd is.
- **Voorstel:** verplaats naar `init_db()` of trigger alleen na een fetch.

**p5 — `_format_eur` en `_display_eur` zijn identiek in twee pages** &middot; `pages/03_balances.py:21-24`, `pages/04_transacties.py:253-257`
- Duplicate implementatie van `€ {format_token(value, decimals=2)}`.
- **Voorstel:** `core/models.format_eur()` of `core/ledger.format_eur()`.

### Nit

**n7 — `import os` mid-file** &middot; `pages/02_fetch.py:82`
- Import na Streamlit-calls; hoort aan de top van het bestand.

**n8 — CSV-bestandsnaam bevat geen jaar-filter** &middot; `pages/04_transacties.py:542`
- `csv_filename(wallet_label, chain_label, asset_label)` — jaar ontbreekt.
- Gebruiker exporteert "2022-filter" maar filename reflecteert dat niet.
- **Voorstel:** voeg `year_label` toe aan `csv_filename()` in `core/ledger.py`.

**n9 — app.py sidebar-caption "Fase 2 — Ledger"** &middot; `app.py:19`
- Stale label; app is al in fase 3.

---

## 5. Code-walkthrough (statisch)

Visuele walkthrough is niet uitgevoerd (niet-interactieve omgeving). Basis-checks:
- **Syntax:** alle pages + `app.py` compileren foutloos (`py_compile`).
- **Imports:** alle `core.*`-modules resolven zonder errors.
- **Tests:** 103 tests groen, geen regressions.

Bevindingen per pagina op basis van code-inspectie:

### Home (`app.py`)

- Sidebar toont 4 pagina-links (wallets / importeren / balansen / transacties)
  en een "Backup maken"-knop. Bij succes toont de knop de bestandsnaam van de
  backup — geen wallet-adressen zichtbaar.
- `st.caption("Fase 2 — Ledger")` in de sidebar (regel 19) is stale (zie n9).
- `init_db()` wordt bij startup aangeroepen — dit triggert ook
  `reclassify_all_token_reviews()` (zie Minor m1 in sectie 2). Geen crash, maar
  trage startup bij grote token-review tabellen.

### Wallets (`pages/01_wallets.py`)

- Kolomvolgorde: Naam | Adres | Laatste fetch. Adres getoond als `st.caption` —
  goed voor privacy (kleiner, grijs).
- "Laatste fetch" toont alleen de datum (`[:10]`), niet de tijd — schoon.
- Confirmation-dialog via session_state werkt correct; "Ja, verwijderen" is
  `type="primary"` (rood), "Annuleren" is secundair — juiste visuele hiërarchie.
- Validatie bij toevoegen: `0x` prefix + lengte 42 — geeft Nederlandse foutmelding.
  UNIQUE-conflict geeft "Dit adres staat al in de lijst." — duidelijk.
- **Ontbrekend:** geen input-sanitatie op de naam-invoer (max-length, geen
  HTML-escaping nodig in Streamlit, maar geen lengte-beperking).

### Importeren (`pages/02_fetch.py`)

- "Haal alle transacties op" + "Alles wissen" naast elkaar — destructieve knop
  niet gemarkeerd als `type="primary"` en heeft geen confirmation direct, maar
  een aparte confirmation-UI verschijnt in session_state. Veilig patroon.
- Fetch-voortgang via `st.progress()` — correct.
- Token-review flow: vier expanders in vaste volgorde (REVIEW → NOISE → IMPORT →
  HIDDEN). Alleen REVIEW is standaard open (of NOISE als REVIEW leeg is) — juiste
  default.
- Statuslabels: "Zeker goed / Onbekend / Verdacht / Scam" — consistent Nederlands.
- Bulk-knoppen ("Voorstel toepassen", "Scams afwijzen", "Alles uitvinken") geven
  expliciete `st.success()`-feedback met aantallen — goed.
- Handmatige waardering-expander: `SelectboxColumn` met opties "Marktprijs /
  Onbekend / Handmatig 0 / Waardeloos" — duidelijke labels. Sla-knop geeft
  ValueError-feedback bij ongeldige datum — `st.error()` correct.
- **Let op:** "Alles wissen" reset ook alle token_review instellingen
  (zie `_reset_inbox()`, regel 59). De warning-tekst vermeldt "token-instellingen",
  maar een gebruiker kan dit over het hoofd zien.

### Balansen (`pages/03_balances.py`)

- Vier kolommetrics: Tokens | Positief saldo | Negatief | Waarde EUR.
- "Waarde EUR" toont "Niet geladen" vóór klik op "Laad EUR-prijzen" — correct.
- Bij partieel bekende EUR: `delta="deels onbekend"` op de metric — zichtbaar.
- Overzicht per asset: samengevat per ticker met expander voor detail per
  wallet/chain. Consistent met detail-view hieronder.
- `"deels onbekend"` marker: verschijnt in asset-titel (regel 71) én in de
  Status-kolom (regel 82) — consistent binnen de pagina.
- On-chain verificatie: ✅/⚠️/❓/❌ in eerste kolom + caption-legenda — helder.
  `❓ = decimals nog onbekend (re-fetch om te populeren)` — correcte instructie.
- BEAM-staking sectie: apart onder divider met "Laad BEAM staking saldo"-knop.
  Saldo telt **niet** mee in portfolio-totaal (zie Minor p1 in sectie 4).
  Sectie-titel en caption maken dit voldoende duidelijk, maar de portfolio-metric
  bevat geen expliciete vermelding.
- Bridge-expander: conditioneel zichtbaar alleen als `bridge_summary` niet leeg is.
  🌉/⚠️-legenda staat onder de tabel — goed geplaatst.

### Transacties (`pages/04_transacties.py`)

- Zes filter-dropdowns in één rij: Wallet | Chain | Jaar | Token | Weergave | Sortering.
  Jaar-filter default: meest recente jaar (`index=1 if years else 0`) — goede UX.
- "Laad EUR op tx-datum"-knop: context-key bevat wallet/chain/jaar maar **niet**
  asset. Gevolg: EUR blijft geladen bij asset-filter-switch — correct gedrag
  (subset van al geladen EUR).
- **Twee views — "Transacties" vs. "Boekingsregels":**
  - "Transacties" toont gegroepeerde rijen (Uit | In | Gas kolommen).
  - "Boekingsregels" toont individuele rijen (Bedrag | Asset kolommen).
  - Labeling is conceptueel juist, maar de volgorde in de dropdown zet
    "Transacties" als eerste — dat is de Boekingsregels-gebundelde weergave.
    Dit kan voor beginners verwarrend zijn (zie ook Minor p3).
- CSV-export: knop altijd zichtbaar, ook bij lege filterset. Exporteert de
  actieve view (gegroepeerd of individueel) — correct.
  Bestandsnaam bevat wallet/chain/asset maar niet jaar (zie Nit n8).
- "Acties aanvullen"-knop: progress-feedback + `st.success()` met aantallen.
  `st.warning()` per fout in `summary.errors` — correcte error-handling.
- Lege filterset: `st.info("Geen transacties gevonden voor deze filters.")` +
  een lege dataframe. Geen crash.
- Metric-dubbeling bij "Boekingsregels"-view (zie Minor p3).

### Datum/bedrag-formattering (cross-page)

- Timestamp: `YYYY-MM-DD HH:MM:SS` via `_display_timestamp()` — consistent op
  transacties-pagina.
- Bedragen: Nederlandse decimaal-komma via `format_token()` X-replace hack.
  Consistent op alle pages die `format_token` uit `core.models` importeren.
- EUR: `€ {format_token(value, decimals=2)}` — consistent (twee aparte functies
  met identiek resultaat; zie Minor p5).

### Statuslabels-consistentie

- `pages/02_fetch.py` "Status"-kolom: token review-status in Nederlands
  ("Zeker goed / Onbekend / Verdacht / Scam").
- `pages/03_balances.py` "Status"-kolom: EUR-volledigheid ("deels onbekend" of leeg).
- Dit zijn **twee verschillende concepten** die toevallig beide "Status" heten
  op verschillende pagina's. Geen actieve verwarring voor de gebruiker omdat ze
  op aparte pagina's staan met andere context. Acceptabel als Nit.

---

## 6. Doorwerking naar fase 4

Fase 3 is afgerond. Onderstaande classificatie bepaalt wat vóór fase 4 geadresseerd
moet worden versus wat later kan.

### Moet vóór fase 4

**M1 — `to_decimal()` silent fallback naar 0** (`core/models.py:125-130`)
- Fase 4 werkt met schema-uitbreidingen en meer data-paths. Een stille 0
  op parse-fouten is een klasse-bug die bij elke nieuwe data-bron kan opspelen.
- Voeg `to_decimal_strict()` toe of log een warning in `to_decimal()`. Laag
  effort, hoog rendement als vangnet.

**M2 — Geen tests voor `core/balance_check.py`**
- Balance-check is de safety-feature die "ETH 96"-type discrepanties opspoort.
  Als fase 4 het schema of de balansen-logica aanpast, moet dit test-net er al zijn.

**M3 — Geen tests voor fetcher-dedup-logica** (`core/fetcher.py:113-310`)
- De dedup-key `(tx_hash, wallet_id, source)` is de kern-correctheid van fase 1.
  Schema-unificatie of fetcher-refactor in fase 4 zonder dit test-net is high-risk.

### Planbaar voor fase 4-kickoff

**M6/M7 — 400-regel splits** (`core/token_review.py`, `pages/02_fetch.py`, `pages/04_transacties.py`)
- Niet urgent voor correctheid, wel onderhoudsdrempel voor fase 4-werk.
- Plan dit als eigen blok bij de fase 4-kickoff.

**P1/P2/P4 — Embedded SQL extraheren naar `core/`**
- `core/wallets.py` (wallets CRUD) en query-extractie naar `core/ledger.py`
  zijn verstandig vóór fase 4 als die fase nieuwe pages of API-endpoints toevoegt
  die dezelfde data-toegang nodig hebben.

**M4 — N×`sqlite3.connect()` in `_upsert_token_review`**
- Voelbaar bij grote eerste fetch. Planbaar bij optimalisatie-blok.

### Kan wachten tot fase 5+

**M5 — Per-rij INSERT + `SELECT changes()`** — performance, niet correctheid.
**m1–m15 / n1–n9 / p1–p6** — alle Minor en Nit. Architectureel wenselijk maar
geen directe fase 4-blocker.

### Niet van toepassing (al afgedekt in fase 3)

Fase 3 heeft een eigen prijs-laag (`core/prices.py`, `core/coingecko.py`,
`core/token_identity.py`, `core/token_valuation.py`) gebouwd bóvenop fase 1+2.
De bevindingen uit deze review raken die laag niet direct — fase 3 is afgerond
en getest (103 tests groen). Fase 4 bouwt verder op de gecombineerde basis.

---

## Bijlagen

### Reviewscope (uit plan)

- Fase 1: `core/db.py`, `core/models.py`, `core/api.py`, `core/parsers.py`,
  `core/fetcher.py`, `core/wrap_reconcile.py`, `core/token_review.py`,
  `core/balance_check.py`, `core/staking.py`, `core/backup.py`,
  `app.py`, `pages/01_wallets.py`, `pages/02_fetch.py`, `pages/03_balances.py`,
  inclusief nagekomen scam-token hardening.
- Fase 2: `pages/04_transacties.py` (incl. CSV-export en groeperingslogica).

### Buiten scope

Fase 3-werk in de werkdirectory (`core/prices.py`, `core/coingecko.py`,
`core/env.py`, `core/token_identity.py`, `core/token_valuation.py`,
`pages/05_jaaroverzicht.py`, alle untracked `tests/test_*`).
