# Review-Opschoon Besluiten

Dit document hoort bij de opschoonronde op `REVIEW_FASE_1_2.md` en staat los
van de faseplanning in `CURRENT.md` en `plans/`.

## Stap 6 - Kleine geparkeerde punten

- **m9 - BEAM staking-cache:** bewust geen cache toegevoegd. De lookup blijft
  live en zit achter een expliciete UI-knop. Er zijn directe tests toegevoegd
  voor de netto berekening en foutafhandeling. Cache pas toevoegen na gemeten
  traagheid bij meerdere wallets.
- **m14 - scam-regex:** geen regexwijziging zonder concreet false-positive
  voorbeeld. Er zijn regressietests toegevoegd dat normale Latijnse
  diakritieken niet direct als scam worden gezien.
- **n2 - `format_token`:** de huidige Nederlandse punt/komma-swap blijft staan.
  Er is een regressietest toegevoegd voor duizendtallen, decimalen en `None`.
- **n6 - `DB_PATH`:** geen env-override toegevoegd. Voor tests blijft monkeypatch
  op `core.db.DB_PATH` de gekozen route; productie gebruikt de macOS
  Application Support locatie.

## Stap 7 - Grote bestandssplitsingen

- **M7 - `core/api.py`:** afgehandeld in stap 5. Etherscan/Routescan blijft in
  `core/api.py`; public-evidence HTTP staat apart in `core/api_public_evidence.py`.
- **P5 - `pages/02_fetch.py`:** gesplitst. De page bevat nu fetch-flow en roept
  `ui.token_intake.render_token_intake()` aan voor de token-review UI.
- **P6 - `pages/04_transacties.py`:** gesplitst. De page bevat filters,
  acties en render-flow; DataFrame/CSV-formattering staat in
  `ui.transaction_tables`.
- **M6 - `core/token_review.py`:** bewust niet blind gesplitst. Dit bestand
  blijft groot, maar splitsen gebeurt pas bij een volgende inhoudelijke
  token-review wijziging zodat de grenzen niet kunstmatig worden.
