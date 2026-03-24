"""
database/queries.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 3 — Database Query Library

Centralized query functions used by all services:
  - indicator engine (Phase 4)
  - ML models (Phase 5)
  - decision engine (Phase 6)
  - backtesting (Phase 5.5)

Import: from database.queries import get_candles, save_indicators, ...
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

import pandas as pd
from datetime import datetime, timezone, timedelta
from loguru import logger
from database.db import DB


# ══════════════════════════════════════════════════════
# MARKET DATA
# ══════════════════════════════════════════════════════

def get_candles(
    symbol: str,
    timeframe: str = "5m",
    limit: int = 500,
    since: datetime | None = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV candles as a pandas DataFrame.
    Used by indicator engine and ML models.

    Args:
        symbol:    e.g. 'BTC/USDT'
        timeframe: e.g. '1m', '5m', '1h'
        limit:     number of most recent candles
        since:     optional start datetime (UTC)

    Returns:
        DataFrame with columns: timestamp, open, high, low, close, volume
        Sorted ascending by timestamp (oldest first).
    """
    if since:
        sql = """
            SELECT timestamp, open, high, low, close, volume
            FROM market_data
            WHERE symbol = %s AND timeframe = %s AND timestamp >= %s
            ORDER BY timestamp ASC
            LIMIT %s;
        """
        params = (symbol, timeframe, since, limit)
    else:
        sql = """
            SELECT timestamp, open, high, low, close, volume
            FROM market_data
            WHERE symbol = %s AND timeframe = %s
            ORDER BY timestamp DESC
            LIMIT %s;
        """
        params = (symbol, timeframe, limit)

    try:
        with DB() as (_, cur):
            cur.execute(sql, params)
            rows = cur.fetchall()

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])

        if not since:
            df = df.sort_values("timestamp").reset_index(drop=True)

        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])

        return df

    except Exception as e:
        logger.error(f"get_candles failed [{symbol}]: {e}")
        return pd.DataFrame()


def get_latest_candle(symbol: str, timeframe: str = "5m") -> dict | None:
    """Get the single most recent candle for a symbol."""
    sql = """
        SELECT timestamp, open, high, low, close, volume
        FROM market_data
        WHERE symbol = %s AND timeframe = %s
        ORDER BY timestamp DESC
        LIMIT 1;
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql, (symbol, timeframe))
            row = cur.fetchone()
        if not row:
            return None
        return dict(zip(["timestamp", "open", "high", "low", "close", "volume"], row))
    except Exception as e:
        logger.error(f"get_latest_candle failed [{symbol}]: {e}")
        return None


def get_candles_range(
    symbol: str,
    start: datetime,
    end: datetime,
    timeframe: str = "5m",
) -> pd.DataFrame:
    """Fetch candles between two datetimes. Used by backtesting."""
    sql = """
        SELECT timestamp, open, high, low, close, volume
        FROM market_data
        WHERE symbol = %s AND timeframe = %s
          AND timestamp BETWEEN %s AND %s
        ORDER BY timestamp ASC;
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql, (symbol, timeframe, start, end))
            rows = cur.fetchall()

        df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col])
        return df
    except Exception as e:
        logger.error(f"get_candles_range failed [{symbol}]: {e}")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════
# INDICATORS
# ══════════════════════════════════════════════════════

def save_indicators(indicators: dict) -> bool:
    """
    Save computed indicators for one candle.

    Args:
        indicators: dict with keys matching indicators table columns.
                    Must include: timestamp, symbol, timeframe
    """
    sql = """
        INSERT INTO indicators
            (timestamp, symbol, timeframe,
             ema_20, ema_50, rsi_14,
             macd, macd_signal, macd_hist,
             atr, bb_upper, bb_middle, bb_lower, adx)
        VALUES
            (%(timestamp)s, %(symbol)s, %(timeframe)s,
             %(ema_20)s, %(ema_50)s, %(rsi_14)s,
             %(macd)s, %(macd_signal)s, %(macd_hist)s,
             %(atr)s, %(bb_upper)s, %(bb_middle)s, %(bb_lower)s, %(adx)s)
        ON CONFLICT (timestamp, symbol, timeframe) DO UPDATE SET
            ema_20     = EXCLUDED.ema_20,
            ema_50     = EXCLUDED.ema_50,
            rsi_14     = EXCLUDED.rsi_14,
            macd       = EXCLUDED.macd,
            macd_signal= EXCLUDED.macd_signal,
            macd_hist  = EXCLUDED.macd_hist,
            atr        = EXCLUDED.atr,
            bb_upper   = EXCLUDED.bb_upper,
            bb_middle  = EXCLUDED.bb_middle,
            bb_lower   = EXCLUDED.bb_lower,
            adx        = EXCLUDED.adx;
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql, indicators)
        return True
    except Exception as e:
        logger.error(f"save_indicators failed [{indicators.get('symbol')}]: {e}")
        return False


def save_indicators_batch(rows: list[dict]) -> int:
    """
    Batch insert indicators for multiple candles.
    Much faster than calling save_indicators() in a loop.
    Returns number of rows saved.
    """
    if not rows:
        return 0

    sql = """
        INSERT INTO indicators
            (timestamp, symbol, timeframe,
             ema_20, ema_50, rsi_14,
             macd, macd_signal, macd_hist,
             atr, bb_upper, bb_middle, bb_lower, adx)
        VALUES
            (%(timestamp)s, %(symbol)s, %(timeframe)s,
             %(ema_20)s, %(ema_50)s, %(rsi_14)s,
             %(macd)s, %(macd_signal)s, %(macd_hist)s,
             %(atr)s, %(bb_upper)s, %(bb_middle)s, %(bb_lower)s, %(adx)s)
        ON CONFLICT (timestamp, symbol, timeframe) DO NOTHING;
    """
    try:
        with DB() as (_, cur):
            cur.executemany(sql, rows)
        logger.info(f"Batch saved {len(rows)} indicator rows")
        return len(rows)
    except Exception as e:
        logger.error(f"save_indicators_batch failed: {e}")
        return 0


def get_indicators(
    symbol: str,
    timeframe: str = "5m",
    limit: int = 500,
) -> pd.DataFrame:
    """Fetch indicators as DataFrame. Used by ML models."""
    sql = """
        SELECT timestamp, ema_20, ema_50, rsi_14,
               macd, macd_signal, macd_hist,
               atr, bb_upper, bb_middle, bb_lower, adx
        FROM indicators
        WHERE symbol = %s AND timeframe = %s
        ORDER BY timestamp DESC
        LIMIT %s;
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql, (symbol, timeframe, limit))
            rows = cur.fetchall()

        cols = ["timestamp", "ema_20", "ema_50", "rsi_14",
                "macd", "macd_signal", "macd_hist",
                "atr", "bb_upper", "bb_middle", "bb_lower", "adx"]
        df = pd.DataFrame(rows, columns=cols)
        df = df.sort_values("timestamp").reset_index(drop=True)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df
    except Exception as e:
        logger.error(f"get_indicators failed [{symbol}]: {e}")
        return pd.DataFrame()


# ══════════════════════════════════════════════════════
# PREDICTIONS
# ══════════════════════════════════════════════════════

def save_prediction(prediction: dict) -> int | None:
    """
    Save ML prediction. Returns the new prediction ID.

    Required keys: timestamp, symbol, timeframe,
                   prob_up, prob_down, model_version
    Optional keys: prob_sideways, features_hash
    """
    sql = """
        INSERT INTO predictions
            (timestamp, symbol, timeframe,
             prob_up, prob_down, prob_sideways,
             model_version, features_hash)
        VALUES
            (%(timestamp)s, %(symbol)s, %(timeframe)s,
             %(prob_up)s, %(prob_down)s, %(prob_sideways)s,
             %(model_version)s, %(features_hash)s)
        RETURNING id;
    """
    prediction.setdefault("prob_sideways", None)
    prediction.setdefault("features_hash", None)

    try:
        with DB() as (_, cur):
            cur.execute(sql, prediction)
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"save_prediction failed: {e}")
        return None


def get_latest_prediction(symbol: str, model_version: str | None = None) -> dict | None:
    """Get the most recent prediction for a symbol."""
    if model_version:
        sql = """
            SELECT id, timestamp, prob_up, prob_down, model_version
            FROM predictions
            WHERE symbol = %s AND model_version = %s
            ORDER BY timestamp DESC LIMIT 1;
        """
        params = (symbol, model_version)
    else:
        sql = """
            SELECT id, timestamp, prob_up, prob_down, model_version
            FROM predictions
            WHERE symbol = %s
            ORDER BY timestamp DESC LIMIT 1;
        """
        params = (symbol,)

    try:
        with DB() as (_, cur):
            cur.execute(sql, params)
            row = cur.fetchone()
        if not row:
            return None
        return dict(zip(["id", "timestamp", "prob_up", "prob_down", "model_version"], row))
    except Exception as e:
        logger.error(f"get_latest_prediction failed: {e}")
        return None


# ══════════════════════════════════════════════════════
# TRADE DECISIONS & TRADES
# ══════════════════════════════════════════════════════

def save_trade_decision(decision: dict) -> int | None:
    """Save a trade decision from the AI engine. Returns decision ID."""
    sql = """
        INSERT INTO trade_decisions
            (timestamp, symbol, action, entry_price,
             stop_loss, take_profit, confidence, reasoning, prediction_id)
        VALUES
            (%(timestamp)s, %(symbol)s, %(action)s, %(entry_price)s,
             %(stop_loss)s, %(take_profit)s, %(confidence)s,
             %(reasoning)s, %(prediction_id)s)
        RETURNING id;
    """
    decision.setdefault("prediction_id", None)
    try:
        with DB() as (_, cur):
            cur.execute(sql, decision)
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"save_trade_decision failed: {e}")
        return None


def save_trade(trade: dict) -> int | None:
    """Save an executed trade. Returns trade ID."""
    sql = """
        INSERT INTO trades
            (timestamp, symbol, side, entry_price,
             quantity, status, decision_id, notes)
        VALUES
            (%(timestamp)s, %(symbol)s, %(side)s, %(entry_price)s,
             %(quantity)s, %(status)s, %(decision_id)s, %(notes)s)
        RETURNING id;
    """
    trade.setdefault("decision_id", None)
    trade.setdefault("notes", None)
    try:
        with DB() as (_, cur):
            cur.execute(sql, trade)
            return cur.fetchone()[0]
    except Exception as e:
        logger.error(f"save_trade failed: {e}")
        return None


def close_trade(trade_id: int, exit_price: float, profit_loss: float, profit_loss_pct: float) -> bool:
    """Update a trade as closed with exit price and P&L."""
    sql = """
        UPDATE trades SET
            closed_at       = NOW(),
            exit_price      = %s,
            profit_loss     = %s,
            profit_loss_pct = %s,
            status          = 'closed'
        WHERE id = %s;
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql, (exit_price, profit_loss, profit_loss_pct, trade_id))
        return True
    except Exception as e:
        logger.error(f"close_trade failed [id={trade_id}]: {e}")
        return False


def get_open_trades() -> list[dict]:
    """Get all currently open trades. Used by risk manager."""
    sql = """
        SELECT id, symbol, side, entry_price, quantity, timestamp
        FROM trades
        WHERE status = 'open'
        ORDER BY timestamp ASC;
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql)
            rows = cur.fetchall()
        cols = ["id", "symbol", "side", "entry_price", "quantity", "timestamp"]
        return [dict(zip(cols, row)) for row in rows]
    except Exception as e:
        logger.error(f"get_open_trades failed: {e}")
        return []


def get_daily_pnl() -> float:
    """Get total P&L for today. Used by risk manager for daily loss limit."""
    sql = """
        SELECT COALESCE(SUM(profit_loss), 0)
        FROM trades
        WHERE status = 'closed'
          AND closed_at >= CURRENT_DATE::timestamptz;
    """
    try:
        with DB() as (_, cur):
            cur.execute(sql)
            return float(cur.fetchone()[0])
    except Exception as e:
        logger.error(f"get_daily_pnl failed: {e}")
        return 0.0
