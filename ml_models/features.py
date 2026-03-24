"""
ml_models/features.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 5 — Feature Engineering

Builds the feature matrix (X) and labels (y) from
market_data + indicators tables for ML training.

Label definition:
  Look 5 candles ahead. If close price goes up >= 0.2% → label=1 (up)
  Otherwise → label=0 (down/sideways)

Features used:
  - All technical indicators (EMA, RSI, MACD, ATR, BB, ADX)
  - Price-derived features (returns, volatility, candle patterns)
  - Normalized versions to remove price scale bias
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

import pandas as pd
import numpy as np
from loguru import logger
from database.queries import get_candles, get_indicators

LOOKAHEAD    = 5
UP_THRESHOLD = 0.002
FEATURE_COLS = [
    "rsi_14",
    "macd_norm",
    "macd_signal_norm",
    "macd_hist_norm",
    "atr_norm",
    "bb_position",
    "bb_width",
    "adx",
    "ema_20_slope",
    "ema_50_slope",
    "ema_cross",
    "return_1",
    "return_3",
    "return_5",
    "volatility_10",
    "candle_body",
    "candle_shadow",
    "volume_ratio",
]

# Numeric columns to cast from Decimal → float
NUMERIC_COLS = [
    "open", "high", "low", "close", "volume",
    "ema_20", "ema_50", "rsi_14", "macd", "macd_signal", "macd_hist",
    "atr", "bb_upper", "bb_middle", "bb_lower", "adx",
]


def build_features(symbol: str, timeframe: str = "5m", limit: int = 50_000) -> pd.DataFrame:
    logger.info(f"Building features for {symbol}...")

    candles    = get_candles(symbol, timeframe=timeframe, limit=limit)
    indicators = get_indicators(symbol, timeframe=timeframe, limit=limit)

    if candles.empty or indicators.empty:
        logger.error(f"Missing data for {symbol}")
        return pd.DataFrame()

    df = pd.merge(candles, indicators, on="timestamp", how="inner")
    df = df.sort_values("timestamp").reset_index(drop=True)

    # ── Fix: cast all numeric cols from Decimal to float ──
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

    logger.info(f"  Merged: {len(df):,} rows")

    # ── Normalized indicator features ──────────────────
    df["macd_norm"]        = df["macd"]        / df["close"]
    df["macd_signal_norm"] = df["macd_signal"] / df["close"]
    df["macd_hist_norm"]   = df["macd_hist"]   / df["close"]
    df["atr_norm"]         = df["atr"]         / df["close"]

    bb_range = df["bb_upper"] - df["bb_lower"]
    df["bb_position"] = (df["close"] - df["bb_lower"]) / bb_range.replace(0, np.nan)
    df["bb_width"]    = bb_range / df["close"]

    df["ema_20_slope"] = df["ema_20"].pct_change(3)
    df["ema_50_slope"] = df["ema_50"].pct_change(3)
    df["ema_cross"]    = (df["ema_20"] - df["ema_50"]) / df["close"]

    # ── Price-derived features ─────────────────────────
    df["return_1"]      = df["close"].pct_change(1)
    df["return_3"]      = df["close"].pct_change(3)
    df["return_5"]      = df["close"].pct_change(5)
    df["volatility_10"] = df["return_1"].rolling(10).std()

    df["candle_body"]   = (df["close"] - df["open"]) / df["atr"].replace(0, np.nan)
    df["candle_shadow"] = (df["high"]  - df["low"])  / df["atr"].replace(0, np.nan)

    vol_ma = df["volume"].rolling(20).mean()
    df["volume_ratio"]  = df["volume"] / vol_ma.replace(0, np.nan)

    # ── Label ──────────────────────────────────────────
    future_close  = df["close"].shift(-LOOKAHEAD)
    future_return = (future_close - df["close"]) / df["close"]
    df["label"]   = (future_return >= UP_THRESHOLD).astype(int)

    # ── Clean up ───────────────────────────────────────
    result = df[["timestamp", "close", "label"] + FEATURE_COLS].copy()
    before = len(result)
    result = result.dropna().reset_index(drop=True)
    after  = len(result)

    logger.info(f"  Features built: {after:,} rows (dropped {before-after:,} NaN rows)")
    logger.info(f"  Label balance: {result['label'].mean():.1%} up signals")

    return result


def get_train_test_split(df: pd.DataFrame, test_ratio: float = 0.2) -> tuple:
    split_idx = int(len(df) * (1 - test_ratio))
    train = df.iloc[:split_idx]
    test  = df.iloc[split_idx:]

    X_train = train[FEATURE_COLS].values
    X_test  = test[FEATURE_COLS].values
    y_train = train["label"].values
    y_test  = test["label"].values

    logger.info(f"  Train: {len(train):,} rows | Test: {len(test):,} rows")
    logger.info(f"  Train label balance: {y_train.mean():.1%} up")
    logger.info(f"  Test  label balance: {y_test.mean():.1%} up")

    return X_train, X_test, y_train, y_test, train, test
