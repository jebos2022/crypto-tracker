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
- [x] `core/db.py` — schema (wallets, transactions, token_review, wallet_chain_state, token_metadata)
- [x] `core/models.py` — CHAINS dict, Decimal helpers
- [x] `core/api.py` — HTTP-laag (tokentx, txlist, txlistinternal, **tokeninfo**)
- [x] `core/fetcher.py` — fetch pipeline, dedup op (tx_hash, wallet_id)
- [x] `core/token_review.py` — scam detectie (regex + metadata), tokeninfo enrichment, accept/reject helpers
- [x] `core/backup.py` — automatische backups
- [x] `pages/01_wallets.py` — wallet management
- [x] `pages/02_fetch.py` — fetch + opt-in token review + metadata verrijken
- [x] `pages/03_balances.py` — balansen per token per wallet

### Testen
- [x] App opstarten: `uv run streamlit run app.py`
- [x] Wallet toevoegen via pagina 01
- [x] Transacties ophalen (alle wallets, alle chains)
- [x] Token review: nieuwe tokens staan standaard UIT
- [x] Token aanvinken → saldo zichtbaar op balansen-pagina
- [ ] ETH-saldo vergelijken met Etherscan website (spot-check)
- [x] Tweede fetch → geen dubbele transacties (incrementeel)
- [x] Inter-wallet transfer: outflow bij wallet A én inflow bij wallet B zichtbaar
- [x] Gas fees: tellen mee als negatief in ETH-saldo
- [x] Negatieve saldi: nul echte negatieve saldi na token review

### Bevindingen / opgeloste punten

- [x] **USD Coin backup Polygon −8.779** — OPGELOST. Nep-token: contract `0xe079490a...`
  is geen officieel USDC-contract op Polygon. Scam drain-token — uitgevinkt in token review.
  Nul negatieve saldi na fix.

- [x] **Waardeloze airdrop-tokens verbergen** — OPGELOST via Etherscan tokeninfo metadata:
  tokens zonder verificatie, website én social media worden als "verdacht" geflagd en
  gescheiden van de clean token lijst. "Aanvinken excl. scams" sluit ook verdachte tokens uit.

- [ ] **Staked tokens** — tokens in een protocol gestaked tellen als aanwezig in balansen
  maar zijn niet vrij beschikbaar. Valt onder Fase 3 (transactieclassificatie). Volgende stap.

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
