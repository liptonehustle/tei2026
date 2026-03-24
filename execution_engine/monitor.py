"""
execution_engine/monitor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 7 — Position Monitor

Checks open trades every minute.
Closes positions when SL or TP is hit.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

from datetime import datetime, timezone
from loguru import logger

from database.queries import get_open_trades
from database.db import DB
from notifications.telegram import alert_position_closed
from notifications.telegram import alert_risk_limit_hit

# STOP_LOSS_PCT   = 0.008   # must match risk_manager
# TAKE_PROFIT_PCT = 0.020


def check_positions(exchange) -> list[dict]:
    """
    Check all open positions against current market prices.
    Returns list of positions that were closed.
    """
    open_trades = get_open_trades()
    if not open_trades:
        return []

    closed = []

    for trade in open_trades:
        symbol      = trade["symbol"]
        side        = trade["side"]
        entry_price = float(trade["entry_price"])
        quantity    = float(trade["quantity"])
        trade_id    = trade["id"]

        # Get ATR from DB
        try:
            with DB() as (_, cur):
                cur.execute("""
                    SELECT atr FROM indicators
                    WHERE symbol = %s AND timeframe = '5m'
                    ORDER BY timestamp DESC LIMIT 1
                """, (symbol,))
                row = cur.fetchone()
                atr = float(row[0]) if row else 0
        except Exception:
            atr = 0

        sl_dist = atr * 1.5 if atr > 0 else entry_price * 0.005
        tp_dist = atr * 2.0 if atr > 0 else entry_price * 0.010

        if side == "buy":
            sl = entry_price - sl_dist
            tp = entry_price + tp_dist
        else:
            sl = entry_price + sl_dist
            tp = entry_price - tp_dist

        # Get current price
        try:
            with DB() as (_, cur):
                cur.execute("""
                    SELECT high, low, close FROM market_data
                    WHERE symbol = %s AND timeframe = '5m'
                    ORDER BY timestamp DESC LIMIT 1
                """, (symbol,))
                row = cur.fetchone()
                if not row:
                    continue
                candle_high, candle_low, current_price = float(row[0]), float(row[1]), float(row[2])
        except Exception as e:
            logger.error(f"Could not fetch candle for {symbol}: {e}")
            continue

        # Check SL/TP
        exit_price  = None
        exit_reason = None

        if side == "buy":
            if candle_low <= sl:
                exit_price, exit_reason = sl, "stop_loss"
            elif candle_high >= tp:
                exit_price, exit_reason = tp, "take_profit"
        else:
            if candle_high >= sl:
                exit_price, exit_reason = sl, "stop_loss"
            elif candle_low <= tp:
                exit_price, exit_reason = tp, "take_profit"

        # Check max hold time (60 candles × 5m = 300 minutes)
        entry_time = trade["timestamp"]
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - entry_time).total_seconds() / 60
        if age_minutes >= 300 and exit_price is None:
            exit_price, exit_reason = current_price, "timeout"
        # Check liquidation price
        from execution_engine.risk_manager import LEVERAGE
        maintenance_margin = 0.005
        if side == "buy":
            liq_price = entry_price * (1 - 1/LEVERAGE + maintenance_margin)
            if current_price <= liq_price * 1.05:  # 5% buffer before liquidation
                exit_price, exit_reason = current_price, "near_liquidation"
                logger.warning(f"⚠️ {symbol} near liquidation! price={current_price:.4f} liq={liq_price:.4f}")
                alert_risk_limit_hit(f"{symbol} near liquidation — emergency close at {current_price:.4f}")
        else:
            liq_price = entry_price * (1 + 1/LEVERAGE - maintenance_margin)
            if current_price >= liq_price * 0.95:  # 5% buffer before liquidation
                exit_price, exit_reason = current_price, "near_liquidation"
                logger.warning(f"⚠️ {symbol} near liquidation! price={current_price:.4f} liq={liq_price:.4f}")
                alert_risk_limit_hit(f"{symbol} near liquidation — emergency close at {current_price:.4f}")

        if exit_price:
            from execution_engine.executor import close_position
            success = close_position(trade_id, symbol, side, quantity)
            if success:
                pnl = (exit_price - entry_price) * quantity \
                      if side == "buy" else \
                      (entry_price - exit_price) * quantity

                logger.info(
                    f"{'✅' if pnl > 0 else '❌'} {symbol} {side.upper()} closed "
                    f"[{exit_reason}] | entry={entry_price:.4f} exit={exit_price:.4f} "
                    f"P&L={pnl:+.4f} USDT"
                    
                )
                alert_position_closed(symbol, side, quantity, entry_price, exit_price, pnl, exit_reason)
                
                closed.append({
                    "trade_id":    trade_id,
                    "symbol":      symbol,
                    "exit_reason": exit_reason,
                    "pnl":         pnl,
                })
        else:
            unrealized = (current_price - entry_price) * quantity \
                        if side == "buy" else \
                        (entry_price - current_price) * quantity
            logger.info(
                f"  📊 {symbol} {side.upper()} | "
                f"entry={entry_price:.4f} now={current_price:.4f} "
                f"H={candle_high:.4f} L={candle_low:.4f} "
                f"unrealized={unrealized:+.4f} USDT | "
                f"SL={sl:.4f} TP={tp:.4f}"
            )

    return closed
