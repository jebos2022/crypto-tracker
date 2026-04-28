# Checklist — Crypto Tracker

Dit document bijhouden per sessie. Afvinken = gedaan en getest.

---

## Setup

- [x] Nieuwe map aangemaakt (`crypto-tracker/`)
- [x] Git repo geïnitialiseerd
- [x] uv project + dependencies (streamlit, httpx, python-dotenv)
- [x] CLAUDE.md + project_spec.md geschreven
- [x] GitHub repo aangemaakt en gekoppeld
- [x] `.env` aanmaken met API keys (`cp .env.example .env`)

---

## Fase 1 — MVP: On-chain import

### Bouwen
- [x] `core/db.py` — schema (wallets, transactions, token_review, wallet_chain_state)
- [x] `core/models.py` — CHAINS dict, Decimal helpers
- [x] `core/api.py` — HTTP-laag (tokentx, txlist, txlistinternal)
- [x] `core/fetcher.py` — fetch pipeline, dedup op (tx_hash, wallet_id)
- [x] `core/backup.py` — automatische backups
- [x] `pages/01_wallets.py` — wallet management
- [x] `pages/02_fetch.py` — fetch + opt-in token review
- [x] `pages/03_balances.py` — balansen per token per wallet

### Testen
- [ ] App opstarten: `uv run streamlit run app.py`
- [ ] Wallet toevoegen via pagina 01
- [ ] Transacties ophalen (start met 1 wallet, 1 chain)
- [ ] Token review: nieuwe tokens staan standaard UIT
- [ ] Token aanvinken → saldo zichtbaar op balansen-pagina
- [ ] ETH-saldo vergelijken met Etherscan website (spot-check)
- [ ] Tweede fetch → geen dubbele transacties (incrementeel)
- [ ] Inter-wallet transfer: outflow bij wallet A én inflow bij wallet B zichtbaar
- [ ] Gas fees: tellen mee als negatief in ETH-saldo

### Bevindingen / openstaande punten

- [ ] **USD Coin backup Polygon −8.779** — backup wallet stuurde 2× 4389,57 USDC naar main
  (zelfde tx_hash bevestigd), maar de bron van die USDC ontbreekt. Geen enkele TRANSFER_IN
  voor USD Coin op backup Polygon in de hele geschiedenis. Onderzoeken: bridge-transactie?
  CEX-storting? Andere wallet niet getrackt? Mogelijk handmatige correctie nodig.

- [ ] **Waardeloze airdrop-tokens verbergen** — tokens die duidelijk niks waard zijn (ooit geairdropped,
  niet verkochten) moeten makkelijk uit het overzicht gefilterd kunnen worden. Idee: kolom "verborgen"
  toevoegen aan token_review, of filter op minimale balanswaarde (vereist Fase 2 EUR-prijzen).
- [ ] **Staked tokens** — tokens die in een protocol gestaked zijn tellen op de balansen-pagina als
  aanwezig, maar het is niet zichtbaar dat ze niet vrij beschikbaar zijn. Valt samen met Fase 3
  (transactieclassificatie). Voorlopig acceptabel.

---

## Fase 2 — EUR waarden (nog niet gestart)

- [ ] CoinGecko API integratie (`core/coingecko.py`)
- [ ] `price_cache` tabel toevoegen aan schema
- [ ] Historische EUR-prijs per token per datum ophalen
- [ ] Balansen pagina uitbreiden met EUR-waarde kolom
- [ ] Totale portfolio waarde in EUR op dashboard

---

## Fase 3 — Transactie-classificatie (nog niet gestart)

- [ ] TRANSFER_IN/OUT verfijnen naar BUY, SELL, SWAP_IN, SWAP_OUT, REWARD
- [ ] Staking-transacties herkennen (hardcoded contracten per token)
- [ ] Linked_id voor swap-paren

---

## Fase 4 — Belastingrapport (nog niet gestart)

- [ ] Weighted moving average kostprijs per asset
- [ ] Realiseerde winst/verlies per verkoop
- [ ] Fiscaal jaaroverzicht Box 3 (waarde op 1 januari per jaar)
- [ ] PDF export

---

## Fase 5 — Uitbreidingen (nog niet gestart)

- [ ] Bitcoin (Blockstream of mempool.space API)
- [ ] Bitvavo CSV import
- [ ] Kraken CSV import
- [ ] Delta app CSV import
