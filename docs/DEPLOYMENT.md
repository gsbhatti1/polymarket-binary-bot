# Deployment

## Windows PowerShell

```powershell
cd C:\Users\gsbha\polymarket-binary-bot
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m compileall src
pytest -q
python scripts\smoke_test.py
Copy-Item .env.example .env
notepad .env
python run_bot.py --mode paper --db data\bot.db --market BTC_UP
```

### Git push

```powershell
git init
git remote add origin https://github.com/gsbhatti1/polymarket-binary-bot.git
git add .
git commit -m "initial deterministic bot scaffold"
git branch -M main
git push -u origin main
```

## Linux / VPS

```bash
cd ~/polymarket-binary-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m compileall src
pytest -q
python scripts/smoke_test.py
cp .env.example .env
nano .env
python run_bot.py --mode paper --db data/bot.db --market BTC_UP
```

## Safe release flow

1. Stop bot
2. Backup DB and repo snapshot
3. Pull verified commit from GitHub
4. Re-run compile gate
5. Re-run pytest
6. Re-run smoke test
7. Start paper
8. Verify SQLite
9. Promote to live only after replay parity checks

## Backup commands

### PowerShell

```powershell
Compress-Archive -Path * -DestinationPath ..\polymarket-binary-bot-backup.zip -Force
Copy-Item data\bot.db ..\bot-backup.db -Force
```

### Linux

```bash
zip -r ../polymarket-binary-bot-backup.zip .
cp data/bot.db ../bot-backup.db
```

## SQLite verification

```bash
sqlite3 data/bot.db ".tables"
sqlite3 data/bot.db "select count(*) from orders;"
sqlite3 data/bot.db "select count(*) from fills;"
sqlite3 data/bot.db "select market_id, yes_qty, avg_yes_cost from positions;"
sqlite3 data/bot.db "select kind, amount_usdc, market_id from cash_ledger order by entry_id desc limit 10;"
```
