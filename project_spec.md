# Project Spec — Crypto Portfolio Tracker

## Doel

Een veilige, lokaal draaiende applicatie die al je cryptocurrency-transacties bijhoudt over meerdere
wallets en exchanges. De app geeft je op elk moment inzicht in de totale waarde van je portfolio in
euro's, en genereert automatisch fiscale jaaroverzichten voor de Belastingdienst (Box 3).
Alles draait op jouw eigen machine — geen cloud, geen gedeelde data, geen private keys.

---

## Fase 1 — MVP: On-chain API import (actief)

**Doel:** Correcte balansen per token per wallet op basis van volledige on-chain transactiegeschiedenis.

**In scope:**
- Wallet management (naam + adres, meerdere wallets)
- On-chain import via Etherscan V2 API (Ethereum, Arbitrum, Base, Optimism, Polygon)
- On-chain import via Routescan API (BEAM chain)
- Drie endpoints per wallet+chain: ERC-20 transfers, native transfers, internal transfers
- Incrementele fetch (startblock tracking — alleen nieuwe blokken ophalen)
- Opt-in token review na fetch (scam filter, standaard alles UIT)
- Balansen per token per wallet (som van alle transacties)

**Niet in scope voor fase 1:**
- Bitcoin
- EUR-waarden (CoinGecko)
- Transactie-classificatie (BUY/SELL/SWAP)
- Staking-herkenning
- Belastingrapport
- CSV import (Delta, Etherscan)

---

## Fase 2 — EUR waarden

- CoinGecko integratie (httpx, price_cache tabel)
- Historische EUR-prijzen per datum per token
- Balansen omzetten naar EUR op dashboard

---

## Fase 3 — Transactie-classificatie

- TRANSFER_IN/OUT verfijnen naar BUY, SELL, SWAP_IN, SWAP_OUT, REWARD
- Staking-transacties herkennen (hardcoded contracten per token — geen auto-detect)
- Linked_id voor swap-paren

---

## Fase 4 — Belastingrapport

- Weighted moving average kostprijs per asset
- Realiseerde winst/verlies per verkoop
- Fiscaal jaaroverzicht Box 3 (waarde op 1 januari per jaar)
- PDF export met fpdf2

---

## Fase 5 — Uitbreidingen

- Bitcoin (Blockstream of mempool.space API)
- CEX imports: Bitvavo CSV, Kraken CSV
- Delta app CSV import
