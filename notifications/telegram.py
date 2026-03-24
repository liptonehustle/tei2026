"""
notifications/telegram.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 10 — Telegram Alerts

Sends trading notifications to Telegram:
  - Order executed (buy/sell)
  - Position closed (SL/TP/timeout) + P&L
  - Daily summary (20:00 WIB / 13:00 UTC)
  - Model retrained / rollback
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

import os
import requests
from datetime import datetime, timezone
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_URL   = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"


def _send(message: str) -> bool:
    """Low-level send — never raises, always returns True/False."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram not configured — skipping notification")
        return False
    try:
        resp = requests.post(TELEGRAM_API_URL, json={
            "chat_id":    TELEGRAM_CHAT_ID,
            "text":       message,
            "parse_mode": "HTML",
        }, timeout=10)
        if resp.status_code == 200:
            return True
        logger.warning(f"Telegram send failed: {resp.status_code} {resp.text}")
        return False
    except Exception as e:
        logger.warning(f"Telegram error: {e}")
        return False


# ── Alert functions ────────────────────────────────────

def alert_order_executed(symbol: str, side: str, quantity: float,
                          entry_price: float, trade_id: int):
    """Fired when a new order is placed."""
    emoji = "🟢" if side == "buy" else "🔴"
    msg = (
        f"{emoji} <b>Order Executed</b>\n"
        f"Symbol:  <code>{symbol}</code>\n"
        f"Side:    <b>{side.upper()}</b>\n"
        f"Price:   <code>{entry_price:.4f} USDT</code>\n"
        f"Qty:     <code>{quantity:.6f}</code>\n"
        f"Trade ID: #{trade_id}\n"
        f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
    )
    _send(msg)


def alert_position_closed(symbol: str, side: str, entry_price: float,
                           exit_price: float, profit_loss: float,
                           profit_loss_pct: float, exit_reason: str,
                           trade_id: int):
    """Fired when a position is closed (SL/TP/timeout)."""
    if profit_loss > 0:
        emoji  = "✅"
        result = "WIN"
    else:
        emoji  = "❌"
        result = "LOSS"

    reason_map = {
        "stop_loss":   "🛑 Stop Loss",
        "take_profit": "🎯 Take Profit",
        "timeout":     "⏱ Timeout",
    }
    reason_label = reason_map.get(exit_reason, exit_reason)

    msg = (
        f"{emoji} <b>Position Closed — {result}</b>\n"
        f"Symbol:  <code>{symbol}</code>\n"
        f"Side:    <b>{side.upper()}</b>\n"
        f"Reason:  {reason_label}\n"
        f"Entry:   <code>{entry_price:.4f} USDT</code>\n"
        f"Exit:    <code>{exit_price:.4f} USDT</code>\n"
        f"P&L:     <b>{profit_loss:+.4f} USDT ({profit_loss_pct:+.2f}%)</b>\n"
        f"Trade ID: #{trade_id}\n"
        f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
    )
    _send(msg)


def alert_daily_summary():
    """Fired every day at 13:00 UTC (20:00 WIB)."""
    from database.db import DB
    try:
        with DB() as (_, cur):
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) AS wins,
                    COALESCE(SUM(profit_loss), 0) AS daily_pnl,
                    COALESCE(SUM(profit_loss) FILTER (WHERE profit_loss > 0), 0) AS gross_profit,
                    COALESCE(SUM(profit_loss) FILTER (WHERE profit_loss < 0), 0) AS gross_loss
                FROM trades
                WHERE status = 'closed'
                  AND closed_at >= CURRENT_DATE::timestamptz
            """)
            row = cur.fetchone()

            cur.execute("""
                SELECT COUNT(*) FROM trades WHERE status = 'open'
            """)
            open_count = cur.fetchone()[0]

        total, wins, daily_pnl, gross_profit, gross_loss = row
        total     = total or 0
        wins      = wins or 0
        losses    = total - wins
        win_rate  = (wins / total * 100) if total > 0 else 0
        pnl_emoji = "📈" if daily_pnl >= 0 else "📉"

        msg = (
            f"📊 <b>Daily Summary</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{pnl_emoji} Daily P&L:  <b>{daily_pnl:+.4f} USDT</b>\n"
            f"🎯 Win Rate:  <b>{win_rate:.1f}%</b> ({wins}W / {losses}L)\n"
            f"📋 Trades:    <b>{total}</b> closed today\n"
            f"💰 Profit:   <code>{gross_profit:+.4f} USDT</code>\n"
            f"💸 Loss:     <code>{gross_loss:+.4f} USDT</code>\n"
            f"🔓 Open now: <b>{open_count}</b> positions\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
        )
        _send(msg)

    except Exception as e:
        logger.error(f"Daily summary failed: {e}")
        _send(f"⚠️ Daily summary error: {e}")


def alert_model_retrained(symbol: str, version: str, metrics: dict, trigger: str):
    """Fired when a model is successfully retrained."""
    msg = (
        f"🤖 <b>Model Retrained</b>\n"
        f"Symbol:  <code>{symbol}</code>\n"
        f"Version: <code>{version}</code>\n"
        f"Trigger: <code>{trigger}</code>\n"
        f"AUC:     <code>{metrics.get('roc_auc', 0):.4f}</code>\n"
        f"F1:      <code>{metrics.get('f1', 0):.4f}</code>\n"
        f"Acc:     <code>{metrics.get('accuracy', 0):.4f}</code>\n"
        f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
    )
    _send(msg)


def alert_model_rollback(symbol: str, bad_version: str, reason: str):
    """Fired when a new model is rejected and rolled back."""
    msg = (
        f"⚠️ <b>Model Rollback</b>\n"
        f"Symbol:  <code>{symbol}</code>\n"
        f"Rejected: <code>{bad_version}</code>\n"
        f"Reason:  {reason}\n"
        f"Previous model restored.\n"
        f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
    )
    _send(msg)


def alert_risk_limit_hit(reason: str):
    """Fired when daily loss limit is hit."""
    msg = (
        f"🚨 <b>Risk Limit Hit</b>\n"
        f"Reason: {reason}\n"
        f"No new orders will be placed today.\n"
        f"<i>{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</i>"
    )
    _send(msg)