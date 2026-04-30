# Review-instructies — Crypto Portfolio Tracker

Dit bestand bevat richtlijnen voor code reviews op dit project, los van de
algemene project-instructies in `CLAUDE.md`. Lokale review-tools (`/review`
skill, `code-review` plugin) gebruiken dit als hoogste-prioriteit instructie.

---

## Wat "Important" 🔴 betekent in dit project

Reserveer Important voor bevindingen die fiscale of financiële correctheid
breken. Dit is een belastingrelevante app — een afgeronde balans of een
verkeerd geclassificeerde transactie kan een onjuiste aangifte veroorzaken.

Important is in elk geval:

- **Float gebruikt voor geld.** Alle bedragen moeten via `Decimal` lopen,
  zowel in geheugen als in DB. Kijk specifiek naar `float()`-casts,
  `+`/`-`/`*`/`/` op niet-Decimal numerieken die een geldbedrag voorstellen,
  en `json.loads()` resultaten die zonder conversie in een Decimal-context belanden.
- **Dedup-bug op tx_hash zonder wallet_id.** De UNIQUE constraint én alle
  in-memory dedup-sets moeten `(tx_hash, wallet_id)` als sleutel gebruiken.
  Een dedup op alleen `tx_hash` veroorzaakt verloren inflows bij wallet→wallet transfers.
- **Stille data-loss bij API-fouten.** Rate-limit responses, timeouts, of
  partial pagination mag nooit `last_block` advancen alsof de data compleet was.
  Zie `core/api.py` `_classify` als referentie-implementatie.
- **Gas fees overgeslagen.** Gas fees zijn echte outflows en moeten ook bij
  mislukte transacties (`isError=1`) als GAS_FEE-rij worden opgeslagen.
- **Migratie zonder backwards-compatibele data.** Schema-wijzigingen die
  bestaande rows breken zonder backfill of expliciete migration-script.
- **EUR-conversie met verkeerde datum.** Spotprijs op verkeerde dag, of
  prijs gebruikt zonder check of die voor de transactiedatum geldt.
- **Onveilige CSV-import.** SQL injection via geparseerde velden, niet-gevalideerde
  decimal parsing die overflow of negatie kan veroorzaken.
- **Missing `txlistinternal`.** Native token-bewegingen via smart contracts
  (DEX returns, unstake) niet ophalen → negatief saldo.
- **Belastingberekening fout.** Onjuiste toepassing van WMA, REWARD niet als
  inkomst geteld, transfer tussen eigen wallets als BUY/SELL geclassificeerd.

## Wat "Nit" 🟡 is (max)

- Streamlit UI-styling, kolomvolgorde, kleuren
- Naamgeving die niet ambigu is
- Imports niet alfabetisch
- Comments die niet schaden
- f-string vs `.format()` keuzes
- Lokalisatie-formattering (komma vs punt) tenzij het een EUR-bedrag betreft

## Cap op nits

Maximaal **5 Nits per review**. Als er meer zijn, zeg in de samenvatting
"plus N vergelijkbare items". Als alles Nits zijn: open de samenvatting met
"Geen blokkerende issues".

## Niet rapporteren

- Style/formatting dat een formatter zou oplossen (we gebruiken geen verplichte formatter)
- Test-coverage tenzij een specifieke test ontbreekt voor een Important-class bug
- TypeError-mogelijkheden in puur Streamlit-render-code waar None acceptabel is
- Generated files (geen in dit project, maar voor de zekerheid)

## Altijd checken bij dit project

- **Decimal door de hele keten.** Volg een geldbedrag van API-input → parser →
  DB-write → DB-read → display. Float ergens in de keten = Important.
- **Bestand onder 400 regels** (CLAUDE.md sectie 2). Over de limiet = Nit,
  tenzij het een refactor-blok is dat juist daar over gaat.
- **`core/api.py` raakt geen DB.** HTTP-laag moet schoon blijven.
- **`core/fetcher.py` doet geen HTTP.** Alleen `core.api.*` aanroepen.
- **Pages bevatten geen business logic.** Roepen `core.*` aan en renderen.
- **Bridge en staking detection.** Nieuwe transfer-classificaties moeten check
  doen tegen `BRIDGE_CONTRACTS` en `STAKED_TOKENS` in `core/models.py`.
- **Test-scenarios uit project_spec.md** — controleer of de blok-acceptatiecriteria
  daadwerkelijk gedekt zijn door wat is gewijzigd.

## Verificatie-eis

Beweringen over runtime-gedrag moeten een `bestand:regel` citaat hebben uit de
broncode, niet een afleiding uit naamgeving. Een review-comment zoals
"Decimal wordt hier verloren" moet wijzen naar de regel waar het gebeurt.

## Re-review gedrag

Bij een tweede review op dezelfde branch: onderdruk nieuwe Nits, alleen
Important-bevindingen posten. Een one-line fix moet niet leiden tot review-ronde 7
op stijl.

## Samenvatting-vorm

Open elke review-samenvatting met een tally:
`{N} Important, {M} Nits` — of "Geen Important issues" als N=0.

Daarna max 3 zinnen context. Geen lange uitleg in de samenvatting; details horen
in de inline comments.
