"""
data_processing/indicator_engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 4 — Indicator Engine

Reads candles from PostgreSQL, computes technical indicators,
saves results back to indicators table.

Indicators computed:
  EMA 20, EMA 50       — trend direction
  RSI 14               — momentum / overbought-oversold
  MACD, Signal, Hist   — trend momentum
  ATR 14               — volatility
  Bollinger Bands      — price channels
  ADX 14               — trend strength

Run modes:
  Backfill all history:  python -m data_processing.indicator_engine --mode backfill
  Latest candle only:    python -m data_processing.indicator_engine --mode latest
  Scheduler (every 1m):  python -m data_processing.indicator_engine --mode scheduler
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse
import os
import sys
import time
import signal

sys.path.insert(0, ".")

import pandas as pd
import numpy as np
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from database.queries import (
    get_candles, save_indicators_batch, get_indicators
)
from database.db import test_connection

os.makedirs("logs", exist_ok=True)
logger.add("logs/indicator_engine.log", rotation="10 MB", retention="7 days", level="INFO")

# ── Config ─────────────────────────────────────────────────
SYMBOLS   = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAME = "5m"

# Minimum candles needed to compute all indicators
# ADX needs the most warmup (~28 candles)
MIN_CANDLES = 60


# ══════════════════════════════════════════════════════════
# INDICATOR CALCULATIONS (using ta library)
# ══════════════════════════════════════════════════════════

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all technical indicators on a OHLCV DataFrame.

    Args:
        df: DataFrame with columns [timestamp, open, high, low, close, volume]
            Must be sorted ascending (oldest first).

    Returns:
        DataFrame with all indicator columns added.
        Rows with NaN indicators (warmup period) are dropped.
    """
    if len(df) < MIN_CANDLES:
        logger.warning(f"Not enough candles ({len(df)}) to compute indicators")
        return pd.DataFrame()

    try:
        from ta.trend import EMAIndicator, MACD, ADXIndicator
        from ta.momentum import RSIIndicator
        from ta.volatility import AverageTrueRange, BollingerBands

        close  = df["close"]
        high   = df["high"]
        low    = df["low"]

        # EMA
        df["ema_20"] = EMAIndicator(close, window=20).ema_indicator()
        df["ema_50"] = EMAIndicator(close, window=50).ema_indicator()

        # RSI
        df["rsi_14"] = RSIIndicator(close, window=14).rsi()

        # MACD
        macd_obj        = MACD(close, window_slow=26, window_fast=12, window_sign=9)
        df["macd"]      = macd_obj.macd()
        df["macd_signal"]= macd_obj.macd_signal()
        df["macd_hist"] = macd_obj.macd_diff()

        # ATR
        df["atr"] = AverageTrueRange(high, low, close, window=14).average_true_range()

        # Bollinger Bands
        bb              = BollingerBands(close, window=20, window_dev=2)
        df["bb_upper"]  = bb.bollinger_hband()
        df["bb_middle"] = bb.bollinger_mavg()
        df["bb_lower"]  = bb.bollinger_lband()

        # ADX
        df["adx"] = ADXIndicator(high, low, close, window=14).adx()

        # Drop warmup rows (NaN values from indicator calculation)
        indicator_cols = ["ema_20", "ema_50", "rsi_14", "macd", "atr", "bb_upper", "adx"]
        df = df.dropna(subset=indicator_cols).reset_index(drop=True)

        return df

    except Exception as e:
        logger.error(f"Indicator computation failed: {e}")
        return pd.DataFrame()


def df_to_indicator_rows(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    """Convert computed DataFrame rows to dicts for batch DB insert."""
    rows = []
    for _, row in df.iterrows():
        rows.append({
            "timestamp":   row["timestamp"],
            "symbol":      symbol,
            "timeframe":   timeframe,
            "ema_20":      None if pd.isna(row["ema_20"])      else float(row["ema_20"]),
            "ema_50":      None if pd.isna(row["ema_50"])      else float(row["ema_50"]),
            "rsi_14":      None if pd.isna(row["rsi_14"])      else float(row["rsi_14"]),
            "macd":        None if pd.isna(row["macd"])        else float(row["macd"]),
            "macd_signal": None if pd.isna(row["macd_signal"]) else float(row["macd_signal"]),
            "macd_hist":   None if pd.isna(row["macd_hist"])   else float(row["macd_hist"]),
            "atr":         None if pd.isna(row["atr"])         else float(row["atr"]),
            "bb_upper":    None if pd.isna(row["bb_upper"])    else float(row["bb_upper"]),
            "bb_middle":   None if pd.isna(row["bb_middle"])   else float(row["bb_middle"]),
            "bb_lower":    None if pd.isna(row["bb_lower"])    else float(row["bb_lower"]),
            "adx":         None if pd.isna(row["adx"])         else float(row["adx"]),
        })
    return rows


# ══════════════════════════════════════════════════════════
# RUN MODES
# ══════════════════════════════════════════════════════════

def backfill_symbol(symbol: str):
    """
    Compute indicators for ALL historical candles of a symbol.
    Run once after Phase 2 backfill.
    Processes in chunks of 2000 candles to avoid memory issues.
    """
    logger.info(f"Backfilling indicators for {symbol}...")

    # Fetch all candles
    df = get_candles(symbol, timeframe=TIMEFRAME, limit=100_000)
    if df.empty:
        logger.warning(f"No candles found for {symbol}")
        return

    logger.info(f"  Loaded {len(df):,} candles — computing indicators...")

    # Compute on full dataset (indicators need full history for accuracy)
    df_computed = compute_indicators(df)
    if df_computed.empty:
        logger.error(f"  Indicator computation returned empty for {symbol}")
        return

    logger.info(f"  Computed {len(df_computed):,} indicator rows — saving to DB...")

    # Batch insert in chunks of 1000
    chunk_size = 1000
    total_saved = 0
    for i in range(0, len(df_computed), chunk_size):
        chunk = df_computed.iloc[i:i+chunk_size]
        rows  = df_to_indicator_rows(chunk, symbol, TIMEFRAME)
        saved = save_indicators_batch(rows)
        total_saved += saved

    logger.success(f"  ✅ {symbol} — {total_saved:,} indicator rows saved")


def backfill_all():
    """Backfill indicators for all configured symbols."""
    logger.info("=" * 55)
    logger.info("Indicator Engine — BACKFILL MODE")
    logger.info("=" * 55)
    for symbol in SYMBOLS:
        backfill_symbol(symbol)
    logger.success("Backfill complete for all symbols.")


def process_latest(symbol: str):
    """
    Compute indicators for the latest candle only.
    Called by the scheduler every minute.
    Fetches last 200 candles for context, saves only the newest indicator row.
    """
    df = get_candles(symbol, timeframe=TIMEFRAME, limit=200)
    if df.empty or len(df) < MIN_CANDLES:
        logger.warning(f"[{symbol}] Not enough candles for live indicator")
        return

    df_computed = compute_indicators(df)
    if df_computed.empty:
        return

    # Only save the latest row
    latest = df_computed.iloc[[-1]]
    rows   = df_to_indicator_rows(latest, symbol, TIMEFRAME)
    save_indicators_batch(rows)

    last = df_computed.iloc[-1]
    logger.info(
        f"✅ {symbol} | "
        f"EMA20={last['ema_20']:.2f} "
        f"RSI={last['rsi_14']:.1f} "
        f"MACD={last['macd']:.4f} "
        f"ADX={last['adx']:.1f}"
    )


def run_latest_all():
    """Process latest candle for all symbols. Called by scheduler."""
    for symbol in SYMBOLS:
        try:
            process_latest(symbol)
        except Exception as e:
            logger.error(f"[{symbol}] process_latest failed: {e}")


# ══════════════════════════════════════════════════════════
# SCHEDULER
# ══════════════════════════════════════════════════════════

def run_scheduler():
    """Run indicator engine every 1 minute via APScheduler."""
    scheduler = BlockingScheduler(timezone="UTC")

    def job():
        run_latest_all()

    scheduler.add_job(job, "interval", minutes=1, id="indicator_engine", max_instances=1)

    def shutdown(signum, frame):
        logger.info("Shutting down indicator scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Indicator Engine scheduler started — running every 1 minute")
    run_latest_all()  # run immediately on start
    scheduler.start()


# ══════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Indicator Engine — Phase 4")
    parser.add_argument(
        "--mode",
        choices=["backfill", "latest", "scheduler"],
        default="backfill",
        help="backfill=all history | latest=one round | scheduler=run every 1min"
    )
    args = parser.parse_args()

    if not test_connection():
        logger.error("PostgreSQL not reachable. Is Docker running?")
        sys.exit(1)

    if args.mode == "backfill":
        backfill_all()
    elif args.mode == "latest":
        run_latest_all()
    elif args.mode == "scheduler":
        run_scheduler()