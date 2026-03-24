"""
strategies/runner.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy Runner

Runs all 5 strategies every cycle:
  1. Evaluate all strategies in parallel
  2. Save ALL signals to strategy_signals table
  3. Select strongest actionable signal
  4. Track virtual P&L for each strategy independently
  5. Update strategy_performance_summary

Returns the selected signal for execution by the decision engine.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

from datetime import datetime, timezone
from loguru import logger

from strategies.base import StrategySignal
from strategies.rsi_mean_reversion   import RSIMeanReversion
from strategies.bb_squeeze_breakout  import BBSqueezeBreakout
from strategies.ema_crossover_volume import EMACrossoverVolume
from strategies.macd_divergence      import MACDDivergence
from strategies.multi_confluence     import MultiConfluence
from database.db import DB

# All strategies — add new ones here
STRATEGIES = [
    RSIMeanReversion(),
    # BBSqueezeBreakout(),
    EMACrossoverVolume(),
    MACDDivergence(),
    MultiConfluence(),
]


# ── Database helpers ───────────────────────────────────

def save_signal(signal: StrategySignal, timeframe: str = "5m") -> int | None:
    """Save a strategy signal to DB. Returns signal ID."""
    sql = """
        INSERT INTO strategy_signals
            (timestamp, strategy_name, symbol, timeframe,
             action, confidence, entry_price, stop_loss,
             take_profit, reasoning, was_selected)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id;
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql, (
                datetime.now(timezone.utc),
                signal.strategy_name,
                signal.symbol,
                timeframe,
                signal.action,
                signal.confidence,
                signal.entry_price,
                signal.stop_loss,
                signal.take_profit,
                signal.reasoning,
                signal.was_selected,
            ))
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"save_signal failed [{signal.strategy_name}]: {e}")
        return None


def open_virtual_trade(signal: StrategySignal, signal_id: int | None, quantity: float = 1.0):
    """Open a virtual trade for a strategy."""
    sql = """
        INSERT INTO strategy_virtual_trades
            (strategy_name, symbol, side, entry_price,
             quantity, status, stop_loss, take_profit,
             signal_id, entry_time)
        VALUES (%s, %s, %s, %s, %s, 'open', %s, %s, %s, %s);
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql, (
                signal.strategy_name,
                signal.symbol,
                signal.action,
                signal.entry_price,
                quantity,
                signal.stop_loss,
                signal.take_profit,
                signal_id,
                datetime.now(timezone.utc),
            ))
    except Exception as e:
        logger.error(f"open_virtual_trade failed [{signal.strategy_name}]: {e}")


def get_open_virtual_trades(strategy_name: str, symbol: str) -> list[dict]:
    """Get open virtual trades for a strategy+symbol."""
    sql = """
        SELECT id, side, entry_price, quantity, stop_loss, take_profit, entry_time
        FROM strategy_virtual_trades
        WHERE strategy_name = %s AND symbol = %s AND status = 'open';
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql, (strategy_name, symbol))
            rows = cur.fetchall()
        cols = ["id", "side", "entry_price", "quantity", "stop_loss", "take_profit", "entry_time"]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        logger.error(f"get_open_virtual_trades failed: {e}")
        return []


def close_virtual_trade(trade_id: int, exit_price: float, exit_reason: str):
    """Close a virtual trade and update performance summary."""
    try:
        with DB() as (_, cur):
            # Get trade details
            cur.execute("""
                SELECT strategy_name, symbol, side, entry_price, quantity
                FROM strategy_virtual_trades WHERE id = %s
            """, (trade_id,))
            row = cur.fetchone()
            if not row:
                return

            strategy_name, symbol, side, entry_price, quantity = row
            entry_price = float(entry_price)
            quantity    = float(quantity)

            # Calculate P&L
            if side == "buy":
                virtual_pnl = (exit_price - entry_price) * quantity
            else:
                virtual_pnl = (entry_price - exit_price) * quantity
            virtual_pnl_pct = virtual_pnl / (entry_price * quantity) * 100

            # Update trade
            cur.execute("""
                UPDATE strategy_virtual_trades SET
                    exit_price      = %s,
                    virtual_pnl     = %s,
                    virtual_pnl_pct = %s,
                    status          = 'closed',
                    exit_reason     = %s,
                    exit_time       = NOW()
                WHERE id = %s
            """, (exit_price, virtual_pnl, virtual_pnl_pct, exit_reason, trade_id))

            # Update performance summary
            is_win = virtual_pnl > 0
            cur.execute("""
                UPDATE strategy_performance_summary SET
                    total_trades    = total_trades + 1,
                    winning_trades  = winning_trades + %s,
                    losing_trades   = losing_trades + %s,
                    total_virtual_pnl = total_virtual_pnl + %s,
                    best_trade_pnl  = GREATEST(best_trade_pnl, %s),
                    worst_trade_pnl = LEAST(worst_trade_pnl, %s),
                    win_rate        = (winning_trades + %s)::float /
                                      NULLIF(total_trades + 1, 0),
                    avg_pnl_per_trade = (total_virtual_pnl + %s) /
                                        NULLIF(total_trades + 1, 0),
                    last_updated    = NOW()
                WHERE strategy_name = %s
            """, (
                1 if is_win else 0,
                0 if is_win else 1,
                virtual_pnl,
                virtual_pnl, virtual_pnl,
                1 if is_win else 0,
                virtual_pnl,
                strategy_name,
            ))

        logger.info(
            f"Virtual trade closed: {strategy_name} {symbol} "
            f"P&L={virtual_pnl:+.4f} [{exit_reason}]"
        )
    except Exception as e:
        logger.error(f"close_virtual_trade failed [{trade_id}]: {e}")


def check_virtual_sl_tp(symbol: str):
    """
    Check all open virtual trades using candle high/low.
    More accurate than spot price — catches intra-candle SL/TP hits.
    Called every 5 minutes when new candle arrives.
    """
    # Get latest candle high/low
    try:
        with DB() as (_, cur):
            cur.execute("""
                SELECT high, low, close FROM market_data
                WHERE symbol = %s AND timeframe = '5m'
                ORDER BY timestamp DESC LIMIT 1
            """, (symbol,))
            row = cur.fetchone()
            if not row:
                return
            candle_high, candle_low, current_price = float(row[0]), float(row[1]), float(row[2])
    except Exception as e:
        logger.error(f"check_virtual_sl_tp candle fetch failed: {e}")
        return

    # Get open virtual trades
    try:
        with DB() as (_, cur):
            cur.execute("""
                SELECT id, strategy_name, side, entry_price, stop_loss, take_profit, entry_time
                FROM strategy_virtual_trades
                WHERE symbol = %s AND status = 'open'
            """, (symbol,))
            rows = cur.fetchall()
    except Exception as e:
        logger.error(f"check_virtual_sl_tp failed: {e}")
        return

    for row in rows:
        trade_id, strategy_name, side, entry_price, sl, tp, entry_time = row
        entry_price = float(entry_price)
        sl = float(sl) if sl else None
        tp = float(tp) if tp else None

        exit_price  = None
        exit_reason = None

        # Use high/low for accurate SL/TP detection
        if side == "buy":
            if sl and candle_low <= sl:
                exit_price, exit_reason = sl, "stop_loss"
            elif tp and candle_high >= tp:
                exit_price, exit_reason = tp, "take_profit"
        else:
            if sl and candle_high >= sl:
                exit_price, exit_reason = sl, "stop_loss"
            elif tp and candle_low <= tp:
                exit_price, exit_reason = tp, "take_profit"

        # Timeout check (300 min)
        if entry_time:
            if entry_time.tzinfo is None:
                entry_time = entry_time.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - entry_time).total_seconds() / 60
            if age_min >= 300 and not exit_price:
                exit_price, exit_reason = current_price, "timeout"

        if exit_price:
            close_virtual_trade(trade_id, exit_price, exit_reason)

def update_signal_count(strategy_name: str):
    """Increment total_signals counter for a strategy."""
    try:
        with DB() as (_, cur):
            cur.execute("""
                UPDATE strategy_performance_summary
                SET total_signals = total_signals + 1,
                    last_updated  = NOW()
                WHERE strategy_name = %s
            """, (strategy_name,))
    except Exception as e:
        logger.error(f"update_signal_count failed: {e}")


def mark_selected(strategy_name: str):
    """Increment times_selected for a strategy."""
    try:
        with DB() as (_, cur):
            cur.execute("""
                UPDATE strategy_performance_summary
                SET times_selected = times_selected + 1,
                    last_updated   = NOW()
                WHERE strategy_name = %s
            """, (strategy_name,))
    except Exception as e:
        logger.error(f"mark_selected failed: {e}")


# ── Main runner ────────────────────────────────────────

def run_strategies(
    symbol:        str,
    indicators:    dict,
    prediction:    dict,
    current_price: float,
    quantity:      float = 1.0,
) -> StrategySignal | None:
    """
    Run all strategies, save all signals, return strongest.

    Args:
        symbol:        trading pair
        indicators:    latest indicator row
        prediction:    ML prediction dict
        current_price: latest close price
        quantity:      virtual position size for P&L tracking

    Returns:
        The strongest actionable signal, or None if all HOLD.
    """
    all_signals  = []
    actionable   = []

    # Check virtual SL/TP for all strategies
    check_virtual_sl_tp(symbol)

    # Evaluate all strategies
    for strategy in STRATEGIES:
        try:
            signal = strategy.evaluate(symbol, indicators, prediction, current_price)
            all_signals.append(signal)
            update_signal_count(strategy.name)

            if signal.action != "hold":
                actionable.append(signal)

        except Exception as e:
            logger.error(f"Strategy {strategy.name} crashed for {symbol}: {e}")

    # Select strongest signal (highest confidence among actionable)
    selected = None
    if actionable:
        selected = max(actionable, key=lambda s: s.confidence)
        selected.was_selected = True
        mark_selected(selected.strategy_name)

    # Save ALL signals to DB
    for signal in all_signals:
        signal_id = save_signal(signal)

        # Open virtual trade for actionable signals
        if signal.action != "hold" and signal.entry_price:
            # Check if strategy already has open virtual trade for this symbol
            open_vt = get_open_virtual_trades(signal.strategy_name, symbol)
            if not open_vt:
                open_virtual_trade(signal, signal_id, quantity)

    # Log summary
    if actionable:
        logger.info(f"  Strategies [{symbol}]: {len(actionable)} actionable signals")
        for s in sorted(actionable, key=lambda x: x.confidence, reverse=True):
            marker = "★" if s == selected else " "
            logger.info(f"  {marker} {s.strategy_name:<25} {s.action.upper():<4} conf={s.confidence:.0%} | {s.reasoning[:60]}")
    else:
        hold_reasons = [f"{s.strategy_name}=HOLD" for s in all_signals]
        logger.info(f"  Strategies [{symbol}]: all HOLD")

    return selected
