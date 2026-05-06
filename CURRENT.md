# Current Work

Laatst bijgewerkt: 2026-05-05.

## Status

- Actieve fase: Fase 3 — EUR-prijslaag (CoinGecko + CoinMarketCap fallback)
- Actief blok: Fase 3 afgerond lokaal
- Actief subblok: wacht op review/merge of fase 4 kickoff
- Branch: `feature/3-a-prices-core`
- Status: subblokken 3.1 t/m 3.10 afgerond en getest; nagekomen 3.5-waarderingsstatus afgerond en getest; klaar voor expliciete review/merge

## Leesvolgorde Voor Nieuwe Chat

1. `AGENTS.md` of `CLAUDE.md`
2. Dit bestand
3. `plans/plan-fase-3.md`
4. Relevante code: `core/prices.py`, `core/rendement.py`, `pages/05_jaaroverzicht.py`, relevante tests in `tests/`

## Huidige Implementatieopdracht

Fase 3 is lokaal afgerond. Ga hierna alleen verder met review/merge of fase 4
kickoff als de gebruiker daar expliciet om vraagt.

Subblok 3.9 is lokaal afgerond:

- `core/rendement.py` met `compute_year(year)`
- contract-aware prijs-id schatting voor de jaaroverzicht-budgetmelding
- voorlopige werkelijk-rendement sectie op `pages/05_jaaroverzicht.py`
- gas als informatiekolom, niet in de nettoformule
- disclaimer dat classificatie in fase 6/8 verfijnd wordt

Subblok 3.10 is lokaal afgerond:

- volledige unittest-suite groen: 103 tests
- py_compile groen voor fase-3 core/pages/tests
- review-fix in `snapshot_for_year()`: ontbrekende nul-balanskant is EUR 0
  in plaats van `—`/deels-onbekend
- geen echte API-calls of DB-output in chat

Run relevante tests:

```bash
uv run python -m unittest discover -s tests
```

## Token-Identiteit

- Opgelost via `core/token_identity.py`: `(chain, contract_address | None) ->
  canonical_asset -> coingecko_id`.
- Bekend: ARB op Arbitrum, BEAM native/WBEAM/bridged ERC-20 en ATH op
  Ethereum/Arbitrum.
- Geen brede symbol fallback toevoegen; fake ARB/BEAM/ATH/OPN/PEAR-contracten
  blijven zonder prijs.
- xOPN/stPEAR zijn staking-wrapperrelaties met stake-event pricing policy. Ze
  mogen niet als gewone token of als simpele underlying-prijsredirect worden
  gewaardeerd; stake/unstake-reconstructie volgt later.

## Handmatige Waardering

- Nagekomen in fase 3.5: `core/token_valuation.py` en extra kolommen op
  `token_review` voor `valuation_status`, `valuation_effective_date` en
  `valuation_reason`.
- `manual_zero` en `worthless` geven vanaf de ingangsdatum EUR 0 in balansen,
  transacties en jaaroverzicht, met duidelijke UI-markering.
- Ontbrekende marktprijzen blijven `—`; er is geen automatische fallback naar 0.
- Fase 6/8 blijven verantwoordelijk voor diepere classificatie, bewijsvoering en
  fiscale rapportage.

## Niet Doen

- Geen echte API-calls doen; tests mocken HTTP.
- Geen merge of destructieve git-acties uitvoeren zonder expliciete opdracht.

## Privacy

- `.env` niet openen of printen.
- Echte database niet dumpen.
- Walletadressen en persoonlijke transacties niet in output zetten.
- Tests moeten tijdelijke databases gebruiken.
