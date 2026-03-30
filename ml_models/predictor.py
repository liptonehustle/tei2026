"""
ml_models/predictor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 5 — Live Predictor

Loads a trained model and generates predictions for
the latest candle. Called by the decision engine.

Usage:
  python -m ml_models.predictor --symbol BTC/USDT
  python -m ml_models.predictor --symbol BTCUSDT --model rf
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

import numpy as np
from loguru import logger

from ml_models.features import build_features, FEATURE_COLS
from ml_models.trainer import load_model, get_latest_version
from database.queries import save_prediction

SYMBOLS   = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAME = "5m"

# Map untuk format symbol (CLI format -> DB format)
SYMBOL_TO_DB = {
    "BTCUSDT": "BTC/USDT",
    "ETHUSDT": "ETH/USDT", 
    "BNBUSDT": "BNB/USDT",
}


def predict_latest(symbol: str, model_type: str = "rf") -> dict | None:
    """
    Generate a prediction for the latest candle of a symbol.
    symbol can be in format "BTCUSDT" or "BTC/USDT"
    """
    # Convert symbol format if needed
    db_symbol = SYMBOL_TO_DB.get(symbol, symbol)
    
    # Load latest saved model
    version = get_latest_version(db_symbol, model_type)
    if not version:
        logger.error(f"No trained model found for {db_symbol} [{model_type}] — run trainer first")
        return None

    model, scaler, meta = load_model(version)

    # Build features (use last 500 candles for context)
    df = build_features(db_symbol, timeframe=TIMEFRAME, limit=500)
    if df.empty:
        logger.error(f"Could not build features for {db_symbol}")
        return None

    # Use the very last row (most recent candle)
    latest_row   = df.iloc[[-1]]
    X            = latest_row[FEATURE_COLS].values
    X_scaled     = scaler.transform(X)

    # Predict
    prob_up      = float(model.predict_proba(X_scaled)[0][1])
    prob_down    = float(1 - prob_up)
    timestamp    = latest_row["timestamp"].iloc[0]

    # Feature hash for reproducibility tracking
    features_hash = hashlib.sha256(X.tobytes()).hexdigest()[:16]

    result = {
        "symbol":        db_symbol,
        "timestamp":     timestamp,
        "timeframe":     TIMEFRAME,
        "prob_up":       round(prob_up, 4),
        "prob_down":     round(prob_down, 4),
        "prob_sideways": None,
        "model_version": version,
        "features_hash": features_hash,
    }

    # Save to DB
    pred_id = save_prediction(result)
    result["prediction_id"] = pred_id

    logger.info(
        f"📊 {db_symbol} | prob_up={prob_up:.2%} prob_down={prob_down:.2%} "
        f"| model={version}"
    )

    return result


def predict_all(model_type: str = "rf") -> list[dict]:
    """Run prediction for all configured symbols."""
    results = []
    for symbol in SYMBOLS:
        pred = predict_latest(symbol, model_type)
        if pred:
            results.append(pred)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ML Predictor — Phase 5")
    parser.add_argument("--symbol", default="all",
                        help="Symbol or 'all'")
    parser.add_argument("--model",  default="rf",
                        choices=["xgb", "rf"],
                        help="Which model to use")
    args = parser.parse_args()

    if args.symbol == "all":
        results = predict_all(args.model)
        logger.info(f"Predictions generated: {len(results)}")
    else:
        predict_latest(args.symbol, args.model)