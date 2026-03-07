# Polymarket Binary Bot

Deterministic Python repo for a **binary-market bot scaffold** with:

- SQLite as source of truth
- Bayesian posterior update
- Kelly sizing for binary YES shares
- enforced exposure caps
- paper/live shared service path
- replay-driven paper execution simulator
- kill switches
- PowerShell and VPS deployment docs

## Critical truth

This repo is **structure-ready** and locally validated, but it is **not guaranteed live-equivalent** until you replay your own captured order books and compare paper fills with live venue behavior.

Use the workflow:

**STOP → Backup → Patch → Run → Verify**

## Features

- **SQLite truth**
  - tables for runs, orders, fills, positions, cash_ledger, realized_pnl, kill_events
- **Strategy**
  - market prior + evidence-driven Bayesian update
  - net-edge thresholding
  - fractional Kelly sizing for binary contracts
- **Execution**
  - paper adapter with replayable order books
  - multi-level book walking
  - partial fill simulation
  - fee basis points support
  - identical service path for paper and live adapters
- **Risk**
  - max market exposure
  - max total exposure
  - max daily loss
  - per-trade notional cap
  - bankroll floor
- **Ops**
  - pytest suite
  - compile gate
  - smoke test
  - PowerShell + VPS instructions

## Repo layout

```text
polymarket-binary-bot/
├── docs/
├── replay/
├── scripts/
├── src/polymarket_bot/
├── tests/
├── run_bot.py
├── requirements.txt
└── pyproject.toml
```

## Quick start

### Windows PowerShell

```powershell
cd C:\Users\YOUR_USER\polymarket-binary-bot
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m compileall src
pytest -q
python scripts\smoke_test.py
python run_bot.py --mode paper --db data\bot.db --market BTC_UP
```

### Linux / VPS

```bash
cd ~/polymarket-binary-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m compileall src
pytest -q
python scripts/smoke_test.py
python run_bot.py --mode paper --db data/bot.db --market BTC_UP
```

## Environment variables

Copy `.env.example` to `.env` and edit if needed.

Main controls:

- `PM_BANKROLL_USDC`
- `PM_PER_TRADE_CAP_USDC`
- `PM_MAX_MARKET_NOTIONAL_USDC`
- `PM_MAX_TOTAL_NOTIONAL_USDC`
- `PM_MAX_DAILY_LOSS_USDC`
- `PM_BANKROLL_FLOOR_USDC`
- `PM_FRACTIONAL_KELLY`
- `PM_MAX_KELLY_FRACTION`
- `PM_MIN_NET_EDGE`
- `PM_PAPER_FEE_BPS`

## Replay format

`replay/sample_btc_book.jsonl` contains one JSON object per line:

```json
{
  "ts": "2026-03-07T15:00:00Z",
  "market_id": "BTC_UP",
  "best_bid": "0.48",
  "best_ask": "0.52",
  "bids": [["0.48", "150"], ["0.47", "300"]],
  "asks": [["0.52", "125"], ["0.53", "300"]]
}
```

## Deterministic operating procedure

1. **STOP** – stop any live process
2. **Backup** – copy DB and zip repo snapshot
3. **Patch** – change code on local PC only
4. **Run** – compile, pytest, smoke test, replay test
5. **Verify** – inspect SQLite tables and logs
6. **Push** – commit + push to GitHub
7. **Deploy** – pull on VPS only after verification

## Status

Local validation in this generated package:
- `python -m compileall src` ✅
- `pytest -q` ✅
- `python scripts/smoke_test.py` ✅

## Next production steps

- wire real Polymarket credentials in live adapter
- capture real order books and compare replay vs live
- add venue reject-path replay
- add settlement/resolution ingestion
- add systemd / supervisor services on VPS
