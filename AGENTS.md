# AGENTS.md / CLAUDE.md — Crypto Portfolio Tracker

Lees dit bestand aan het begin van elke sessie. Dit is het gedeelde agent-contract
voor Claude, ChatGPT/Codex en andere coding agents.

`AGENTS.md` en `CLAUDE.md` horen dezelfde inhoud te hebben. Als je een van beide
aanpast, werk de andere in dezelfde wijziging bij.

## 1. Sessie-start

Lees in deze volgorde:

1. `AGENTS.md` of `CLAUDE.md`
2. `CURRENT.md`
3. Het actieve faseplan in `plans/`
4. Alleen daarna de relevante code en tests

Als de gebruiker vraagt om verder te gaan met een concreet blok of subblok, voer
dat blok uit. Stop niet bij alleen samenvatten van het plan.

## 2. Doel en scope

Lokale crypto portfolio tracker voor macOS. Stack: Python 3.12, Streamlit,
SQLite, httpx, python-dotenv en uv.

Doel:

- on-chain en later exchange-transacties verzamelen;
- portfolio en saldi in EUR tonen;
- fiscale jaaroverzichten voorbereiden voor Box 3 en werkelijk rendement;
- alles lokaal houden.

Niet in scope:

- cloud-backend;
- accounts/auth;
- private keys;
- automatisch handelen;
- data delen met externe diensten buiten expliciet gekozen publieke API-calls.

## 3. Privacy en lokale data

De repo bevat code, documentatie en tests. De echte projectdata blijft lokaal.

Nooit committen:

- `.env` of andere lokale env-bestanden;
- echte SQLite databases;
- SQLite WAL/SHM-bestanden;
- backupbestanden;
- exports met persoonlijke transacties of walletlijsten.

Regels:

- Open of print `.env` niet, tenzij de gebruiker expliciet vraagt om de inhoud te
  inspecteren.
- Dump de echte database niet naar chat of logs.
- Gebruik voor tests tijdelijke databases; zie bestaande tests voor monkeypatches
  op `core.db.get_connection`.
- Echte walletadressen zijn persoonlijke data. Zet ze niet in documentatie of
  eindantwoorden. Redigeer command-output als die echte adressen bevat.
- Publieke contractadressen van tokens, bridges en routers in code zijn wel ok.
- `.env.example` bevat alleen placeholders.
- Als een command mogelijk secrets, walletadressen of persoonlijke transacties
  toont, geef een samenvatting met redactie in plaats van ruwe output.

Lokale database:

- Code gebruikt: `~/Library/Application Support/crypto-tracker/portfolio.db`.
- Oude databases onder `data/` in de repo zijn legacy/lokaal en niet canoniek.
- Zet SQLite-bestanden niet in iCloud Drive of Git.

Backups:

- Backups horen naast de echte lokale database te staan:
  `~/Library/Application Support/crypto-tracker/backups/`.
- Backups horen niet in de repo en niet in Git.

## 4. Documentrollen

- `AGENTS.md` / `CLAUDE.md`: gedeelde agent-instructies, privacyregels,
  architectuurregels en workflow.
- `CURRENT.md`: actuele handoff. Dit is de eerste plek voor "waar zijn we nu?".
- `project_spec.md`: routekaart op hoofdlijnen met fasen, blokken en
  acceptatiecriteria.
- `plans/plan-fase-X.md`: uitgewerkt faseplan na sparsessie/kickoff.
- `CHECKLIST.md`: voortgang. Afvinken betekent: gedaan, getest en klaar om te
  mergen of al gemerged, afhankelijk van de statusnotitie.
- `REVIEW.md`: review-calibratie voor dit project.
- `memory/`: archief of historische context, niet de actuele bron van waarheid.

Als documenten elkaar tegenspreken, geldt:

1. gebruikersinstructie in de huidige sessie;
2. `CURRENT.md`;
3. actief faseplan in `plans/`;
4. `project_spec.md`;
5. `AGENTS.md` / `CLAUDE.md`;
6. oudere memory/archiefbestanden.

Bij twijfel: stop niet automatisch. Inspecteer de repo en maak een conservatieve
keuze. Stel alleen een vraag als een verkeerde aanname risico geeft voor data,
schema of fiscale/financiële correctheid.

## 5. Faseworkflow

Het project werkt in fasen. `project_spec.md` bevat de hoofdlijn; het volledige
detailplan ontstaat pas bij de kickoff van een fase.

Fase-kickoff:

1. Lees `CURRENT.md`, `project_spec.md`, relevante code, tests en bestaande plans.
2. Analyseer scope, risico's en afhankelijkheden.
3. Stel open vragen tot de fase voldoende scherp is.
4. Werk het faseplan uit in `plans/plan-fase-X.md`.
5. Update `CURRENT.md` met actieve fase, taak, branch en expliciete "niet doen".
6. Wacht op akkoord van de gebruiker voordat je fasecode bouwt, tenzij de
   gebruiker expliciet zegt dat je direct moet implementeren.

Implementatie per blok/subblok:

1. Werk alleen aan het actieve blok of subblok.
2. Bouw niet vooruit op latere subblokken zonder expliciete opdracht.
3. Houd wijzigingen klein en in lijn met bestaande patronen.
4. Voeg gerichte tests toe voor schema, geldbedragen, parsing en regressies.
5. Run relevante tests.
6. Rapporteer gewijzigde bestanden en testresultaten.
7. Update `CURRENT.md`, het actieve plan en `CHECKLIST.md` als de status echt
   veranderd is.

## 6. Bestandsstructuur

Belangrijke bestanden:

```text
crypto-tracker/
├── AGENTS.md
├── CLAUDE.md
├── CURRENT.md
├── REVIEW.md
├── project_spec.md
├── CHECKLIST.md
├── plans/
├── memory/
├── app.py
├── pages/
│   ├── 01_wallets.py
│   ├── 02_fetch.py
│   ├── 03_balances.py
│   └── 04_transacties.py
├── core/
│   ├── db.py
│   ├── models.py
│   ├── api.py
│   ├── parsers.py
│   ├── fetcher.py
│   ├── ledger.py
│   ├── token_review.py
│   ├── balance_check.py
│   ├── staking.py
│   └── backup.py
└── tests/
```

Maximaal 400 regels per Python-bestand. Bij ongeveer 350+ regels: splits eerst
als je substantieel gaat toevoegen.

Strikte scheiding:

- `core/api.py` raakt nooit de DB; dit is puur HTTP.
- `core/parsers.py` is pure data-transformatie: raw API-row naar dict.
- `core/fetcher.py` orkestreert: roept `api`, `parsers` en DB/helpers aan, maar
  bevat geen HTTP-code.
- Pages bevatten geen business logic; ze roepen `core.*` aan en renderen.
- Nieuwe externe API's krijgen hun eigen HTTP-laag zonder DB-toegang.

## 7. Database

Volledig schema en idempotente migraties staan in `core/db.py`.

Regels:

- Alle geld- en tokenbedragen als `Decimal` in geheugen.
- Alle Decimal-bedragen als `TEXT` opslaan.
- Nooit `float` gebruiken voor geld of tokenhoeveelheden.
- Schemawijzigingen moeten bestaande lokale databases veilig migreren of expliciet
  in het plan vermelden waarom een reset acceptabel is.
- Transactie-PK is een UUID/string, geen AUTOINCREMENT.

## 8. Kritieke lessen

### Les 1 — Dedup key = `(tx_hash, wallet_id, source)`

Twee onafhankelijke problemen vereisen alle drie velden:

- Cross-wallet: dezelfde on-chain transactie kan bij meerdere wallets verschijnen.
  Zonder `wallet_id` verdwijnt een legitieme inflow/outflow.
- Cross-source: dezelfde outer tx_hash kan in `tokentx` en `txlist` staan. Zonder
  `source` verdwijnt bijvoorbeeld de ETH-outflow bij "koop token met ETH".

Schema-oplossing: `UNIQUE (tx_hash, wallet_id, source)`.
In-memory dedup moet dezelfde logica volgen.

### Les 2 — Altijd drie EVM-endpoints per wallet en chain

1. `tokentx` — ERC-20 transfers
2. `txlist` — native direct sends en gas fees
3. `txlistinternal` — native bewegingen via smart contracts

Zonder `txlistinternal` ontbreken DEX returns, unstake flows en vergelijkbare
native bewegingen.

### Les 3 — Gas fees zijn echte outflows

Gas fees altijd opslaan als aparte `GAS_FEE`-rij, ook bij mislukte transacties.
De EVM rekent gas ongeacht het transactieresultaat.

Formule: `gasUsed * gasPrice / 10^18`.

## 9. Chain- en API-regels

`CHAINS` in `core/models.py` is de bron van waarheid voor EVM-chains.

Etherscan V2:

```text
https://api.etherscan.io/v2/api?chainid={N}&apikey={KEY}&...
```

Routescan voor BEAM:

```text
https://api.routescan.io/v2/network/mainnet/evm/4337/etherscan/api?apikey={KEY}&...
```

API-regels:

- Paginatie: page_size 10.000, `startblock`/`endblock`, stop als resultaat korter
  is dan page_size.
- Respecteer rate limits en advance cursors niet na partial/failed fetches.
- `isError=1`: skip value movement, maar sla gas fee nog steeds op.
- Zero-value internal calls overslaan.
- Synthetic hash voor internal txs: `f"{outer_hash}_int_{global_idx}"`.

## 10. Getallen en opmaak

- Gebruik `Decimal` voor bedragen.
- DB writes: `str(decimal_value)`.
- DB reads: `Decimal(row["amount"])`.
- UI: Nederlandse opmaak waar relevant.
- EUR-prijzen moeten aan de juiste datum gekoppeld zijn; geen stille fallback naar
  verkeerde datum of verkeerde token.

## 11. Git-regels

- `main` is stabiel.
- Werk per blok op een branch zoals `feature/x-y-naam`.
- Commit nooit secrets, databases, backups of persoonlijke exports.
- Commit format: `[fase x.y] korte omschrijving`.
- Revert geen gebruikerswijzigingen tenzij de gebruiker dat expliciet vraagt.
- Als de worktree dirty is, onderscheid jouw wijzigingen van bestaande wijzigingen.

## 12. Commando's

```bash
# Start app
uv run streamlit run app.py

# DB resetten
uv run python -c "from core.db import reset_db; reset_db()"

# Relevante tests
uv run python -m unittest discover -s tests

# Dependency toevoegen
uv add package-naam
```

## 13. Review-flow

Gebruik `REVIEW.md` als project-specifieke review-calibratie.

Reviewprioriteit:

- fiscale of financiële correctheid;
- data-loss;
- schema/migratieproblemen;
- API-cursor/rate-limit problemen;
- Decimal-correctheid;
- regressies in fetch, ledger en balances.

Streamlit-styling en kleine naamgevingszaken zijn nits, tenzij ze financiële
informatie verkeerd of misleidend tonen.
