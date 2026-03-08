"""
Telegram alert system for polymarket-binary-bot.

Sends: trade opens, trade closes, PnL alerts, portfolio snapshots,
       risk blocks, and responds to /status /report /positions commands.
"""
from __future__ import annotations

import logging
import os
import time
from decimal import Decimal

log = logging.getLogger("polymarket-bot")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

_LAST_ALERT_TS = 0.0
_ALERT_COUNT = 0
MAX_ALERTS_PER_MIN = 15


def _enabled() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)


def _send(text: str, parse_mode: str = "HTML") -> bool:
    if not _enabled():
        return False
    try:
        import httpx
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        with httpx.Client(timeout=8) as c:
            r = c.post(url, json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": parse_mode,
            })
            return r.status_code == 200
    except Exception as e:
        log.warning("Telegram send failed: %r", e)
        return False


def _rate_ok() -> bool:
    global _LAST_ALERT_TS, _ALERT_COUNT
    now = time.time()
    if now - _LAST_ALERT_TS >= 60:
        _LAST_ALERT_TS = now
        _ALERT_COUNT = 0
    if _ALERT_COUNT < MAX_ALERTS_PER_MIN:
        _ALERT_COUNT += 1
        return True
    return False


# ── Trade alerts ────────────────────────────────────────────


def send_trade_opened(
    market_id: str,
    side: str,
    qty: Decimal,
    price: Decimal,
    spent: Decimal,
    kelly_frac: Decimal,
    cash: Decimal,
    reason: str,
) -> None:
    if not _rate_ok():
        return
    ts = time.strftime("%H:%M UTC", time.gmtime())
    text = (
        f"🟢 <b>TRADE OPENED</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>{market_id[:50]}</b>\n"
        f"🎯 Side: <b>{side}</b>\n"
        f"📦 Qty: <b>{qty:.2f}</b> @ <b>${price:.4f}</b>\n"
        f"💵 Spent: <b>${spent:.4f}</b>\n"
        f"⚡ Kelly: <b>{kelly_frac * 100:.1f}%</b>\n"
        f"💡 Reason: {reason}\n"
        f"🏦 Cash: <b>${cash:.2f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {ts}"
    )
    _send(text)


def send_trade_closed(
    market_id: str,
    qty: Decimal,
    entry_price: Decimal,
    exit_price: Decimal,
    pnl: Decimal,
    reason: str,
    cash: Decimal,
) -> None:
    if not _rate_ok():
        return
    ts = time.strftime("%H:%M UTC", time.gmtime())
    emoji = "✅" if pnl > 0 else "❌" if pnl < 0 else "➖"
    pnl_str = f"+${pnl:.4f}" if pnl >= 0 else f"-${abs(pnl):.4f}"
    text = (
        f"🔴 <b>TRADE CLOSED</b> {emoji}\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📌 <b>{market_id[:50]}</b>\n"
        f"📦 Qty: <b>{qty:.2f}</b>\n"
        f"📈 Entry: ${entry_price:.4f} → Exit: ${exit_price:.4f}\n"
        f"📊 PnL: <b>{pnl_str}</b>\n"
        f"💡 Reason: {reason}\n"
        f"🏦 Cash: <b>${cash:.2f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {ts}"
    )
    _send(text)


def send_risk_block(market_id: str, reason: str) -> None:
    if not _rate_ok():
        return
    _send(f"⚠️ <b>RISK BLOCK</b>\n{market_id[:40]}\nReason: {reason}")


def send_status(
    bankroll: float,
    cash: float,
    open_notional: float,
    equity: float,
    return_pct: float,
    realized_today: float,
    n_orders: int,
    n_fills: int,
    n_kills: int,
    positions: list[dict] | None = None,
) -> None:
    ts = time.strftime("%H:%M UTC", time.gmtime())
    ret_sign = "+" if return_pct >= 0 else ""
    pnl_sign = "+" if realized_today >= 0 else ""

    text = (
        f"📊 <b>PORTFOLIO STATUS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏦 Bankroll:   <b>${bankroll:,.2f}</b>\n"
        f"💰 Cash:       <b>${cash:,.4f}</b>\n"
        f"📦 Open:       <b>${open_notional:,.4f}</b>\n"
        f"💎 Equity:     <b>${equity:,.4f}</b>\n"
        f"📈 Return:     <b>{ret_sign}{return_pct:.2f}%</b>\n"
        f"📊 PnL today:  <b>{pnl_sign}${realized_today:,.4f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Orders: {n_orders} | Fills: {n_fills} | Blocks: {n_kills}\n"
    )

    if positions:
        text += "\n<b>Open Positions:</b>\n"
        for p in positions[:8]:
            slug = str(p.get("market_id", ""))[:25]
            qty = float(p.get("yes_qty", 0))
            cost = float(p.get("avg_yes_cost", 0))
            text += f"  • {slug} | {qty:.1f} @ ${cost:.3f}\n"

    text += f"\n🕐 {ts}"
    _send(text)


def send_startup(mode: str, markets: list[str], bankroll: float) -> None:
    ts = time.strftime("%H:%M UTC", time.gmtime())
    mkt_str = ", ".join(markets[:5])
    text = (
        f"🚀 <b>BINARY BOT STARTED</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"⚙️ Mode: <b>{mode.upper()}</b>\n"
        f"📌 Markets: <b>{mkt_str}</b>\n"
        f"🏦 Bankroll: <b>${bankroll:,.2f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {ts}"
    )
    _send(text)


def send_shutdown(ticks: int, equity: float, return_pct: float) -> None:
    ts = time.strftime("%H:%M UTC", time.gmtime())
    text = (
        f"🛑 <b>BINARY BOT STOPPED</b>\n"
        f"Ticks: {ticks} | Equity: ${equity:,.4f} | Return: {return_pct:+.2f}%\n"
        f"🕐 {ts}"
    )
    _send(text)


def send_heartbeat(tick: int, cash: float, open_notional: float) -> None:
    _send(f"💓 tick={tick} cash=${cash:.2f} open=${open_notional:.2f}")


# ── Command polling ─────────────────────────────────────────


_UPDATE_OFFSET = 0


def poll_commands() -> list[tuple[str, str]]:
    """Poll Telegram for commands. Returns list of (command, chat_id)."""
    global _UPDATE_OFFSET
    if not _enabled():
        return []
    try:
        import httpx
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        r = httpx.get(url, params={"offset": _UPDATE_OFFSET, "timeout": 1}, timeout=5)
        if r.status_code != 200:
            return []
        data = r.json()
        if not data.get("ok"):
            return []
        commands = []
        for u in data.get("result", []):
            _UPDATE_OFFSET = int(u.get("update_id", 0)) + 1
            msg = u.get("message", {})
            chat = msg.get("chat", {})
            chat_id = str(chat.get("id", ""))
            text = (msg.get("text") or "").strip().lower()
            if chat_id == TELEGRAM_CHAT_ID and text.startswith("/"):
                commands.append((text, chat_id))
        return commands
    except Exception:
        return []
