"""
ml_models/trainer.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 5 — Model Trainer

Trains XGBoost and RandomForest models on indicator features.
Saves models to ml_models/saved/ with version tracking.

Usage:
  python -m ml_models.trainer --symbol BTC/USDT
  python -m ml_models.trainer --symbol BTC/USDT --model xgboost
  python -m ml_models.trainer --symbol all
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse
import os
import sys
import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import joblib
from loguru import logger
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score,
    f1_score, roc_auc_score, classification_report
)
from xgboost import XGBClassifier

from ml_models.features import build_features, get_train_test_split, FEATURE_COLS
from database.db import test_connection

os.makedirs("logs", exist_ok=True)
os.makedirs("ml_models/saved", exist_ok=True)
logger.add("logs/trainer.log", rotation="10 MB", retention="7 days", level="INFO")

SYMBOLS   = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAME = "5m"
SAVED_DIR = Path("ml_models/saved")


# ══════════════════════════════════════════════════════
# MODEL DEFINITIONS
# ══════════════════════════════════════════════════════

def get_xgboost() -> XGBClassifier:
    return XGBClassifier(
        n_estimators=300,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=5,
        scale_pos_weight=1,
        eval_metric="logloss",
        random_state=42,
        verbosity=0,
    )


def get_random_forest() -> RandomForestClassifier:
    return RandomForestClassifier(
        n_estimators=200,
        max_depth=10,
        min_samples_leaf=20,
        max_features="sqrt",
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )


# ══════════════════════════════════════════════════════
# EVALUATION
# ══════════════════════════════════════════════════════

def evaluate(model, X_test, y_test, model_name: str) -> dict:
    """Compute and log evaluation metrics."""
    y_pred      = model.predict(X_test)
    y_pred_prob = model.predict_proba(X_test)[:, 1]

    metrics = {
        "accuracy":  round(accuracy_score(y_test, y_pred), 4),
        "precision": round(precision_score(y_test, y_pred, zero_division=0), 4),
        "recall":    round(recall_score(y_test, y_pred, zero_division=0), 4),
        "f1":        round(f1_score(y_test, y_pred, zero_division=0), 4),
        "roc_auc":   round(roc_auc_score(y_test, y_pred_prob), 4),
    }

    logger.info(f"── {model_name} Evaluation ────────────────────────")
    logger.info(f"  Accuracy:  {metrics['accuracy']:.4f}")
    logger.info(f"  Precision: {metrics['precision']:.4f}")
    logger.info(f"  Recall:    {metrics['recall']:.4f}")
    logger.info(f"  F1 Score:  {metrics['f1']:.4f}")
    logger.info(f"  ROC AUC:   {metrics['roc_auc']:.4f}")

    # Interpretation
    if metrics["roc_auc"] > 0.55:
        logger.success(f"  ✅ ROC AUC {metrics['roc_auc']:.4f} — model has predictive signal")
    else:
        logger.warning(f"  ⚠️  ROC AUC {metrics['roc_auc']:.4f} — weak signal, close to random")

    return metrics


def feature_importance(model, model_name: str):
    """Log top 10 most important features."""
    if hasattr(model, "feature_importances_"):
        importances = model.feature_importances_
        pairs = sorted(zip(FEATURE_COLS, importances), key=lambda x: x[1], reverse=True)
        logger.info(f"── Top 10 features [{model_name}] ──────────────────")
        for feat, imp in pairs[:10]:
            bar = "█" * int(imp * 100)
            logger.info(f"  {feat:<20} {imp:.4f} {bar}")


# ══════════════════════════════════════════════════════
# SAVE / LOAD
# ══════════════════════════════════════════════════════

def save_model(model, scaler, symbol: str, model_type: str, metrics: dict) -> str:
    """
    Save model + scaler + metadata to disk.
    Returns the model version string.
    """
    # Version: e.g. xgb_BTCUSDT_v20260319_1430
    ts      = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    sym_str = symbol.replace("/", "")
    version = f"{model_type}_{sym_str}_v{ts}"

    model_path  = SAVED_DIR / f"{version}.joblib"
    scaler_path = SAVED_DIR / f"{version}_scaler.joblib"
    meta_path   = SAVED_DIR / f"{version}_meta.json"

    joblib.dump(model,  model_path)
    joblib.dump(scaler, scaler_path)

    meta = {
        "version":    version,
        "symbol":     symbol,
        "model_type": model_type,
        "timeframe":  TIMEFRAME,
        "features":   FEATURE_COLS,
        "metrics":    metrics,
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logger.success(f"  Model saved: {model_path}")
    return version


def load_model(version: str):
    """Load a saved model + scaler by version string."""
    model_path  = SAVED_DIR / f"{version}.joblib"
    scaler_path = SAVED_DIR / f"{version}_scaler.joblib"
    meta_path   = SAVED_DIR / f"{version}_meta.json"

    model  = joblib.load(model_path)
    scaler = joblib.load(scaler_path)
    with open(meta_path) as f:
        meta = json.load(f)

    return model, scaler, meta


def get_latest_version(symbol: str, model_type: str) -> str | None:
    """Find the most recently saved model version for a symbol + type."""
    sym_str = symbol.replace("/", "")
    pattern = f"{model_type}_{sym_str}_v"
    versions = [f.stem for f in SAVED_DIR.glob(f"{pattern}*.joblib")
                if "_scaler" not in f.stem]
    if not versions:
        return None
    return sorted(versions)[-1]  # latest by timestamp in name


# ══════════════════════════════════════════════════════
# TRAIN
# ══════════════════════════════════════════════════════

def train_symbol(symbol: str, model_type: str = "both") -> dict:
    logger.info("=" * 55)
    logger.info(f"Training: {symbol} | model: {model_type}")
    logger.info("=" * 55)
    
    # Build features
    df = build_features(symbol, timeframe=TIMEFRAME)
    if df.empty:
        logger.error(f"No features built for {symbol}")
        return {}
    
    # Validasi label balance
    positive_labels = df['label'].sum()
    if positive_labels < 10:
        logger.warning(f"⚠️ {symbol}: only {positive_labels} positive labels — skipping")
        return {}
    
    logger.info(f"  Label balance: {positive_labels/len(df):.1%} ({positive_labels}/{len(df)})")

    X_train, X_test, y_train, y_test, train_df, test_df = get_train_test_split(df)

    # Scale features
    scaler  = StandardScaler()
    X_train = scaler.fit_transform(X_train)
    X_test  = scaler.transform(X_test)

    versions = {}

    # ── XGBoost ───────────────────────────────────────
    if model_type in ("xgboost", "both"):
        logger.info("Training XGBoost...")
        xgb = get_xgboost()
        xgb.fit(
            X_train, y_train,
            eval_set=[(X_test, y_test)],
            verbose=False,
        )
        metrics = evaluate(xgb, X_test, y_test, "XGBoost")
        feature_importance(xgb, "XGBoost")
        version = save_model(xgb, scaler, symbol, "xgb", metrics)
        versions["xgboost"] = version
        logger.success(f"XGBoost done → version: {version}")

    # ── Random Forest ─────────────────────────────────
    if model_type in ("rf", "both"):
        logger.info("Training Random Forest...")
        rf = get_random_forest()
        rf.fit(X_train, y_train)
        metrics = evaluate(rf, X_test, y_test, "RandomForest")
        feature_importance(rf, "RandomForest")
        version = save_model(rf, scaler, symbol, "rf", metrics)
        versions["rf"] = version
        logger.success(f"RandomForest done → version: {version}")

    return versions


# ══════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ML Model Trainer — Phase 5")
    parser.add_argument("--symbol", default="BTC/USDT",
                        help="Symbol to train on, or 'all' for all symbols")
    parser.add_argument("--model",  default="both",
                        choices=["xgboost", "rf", "both"],
                        help="Which model to train")
    args = parser.parse_args()

    if not test_connection():
        logger.error("PostgreSQL not reachable.")
        sys.exit(1)

    if args.symbol == "all":
        for symbol in SYMBOLS:
            train_symbol(symbol, args.model)
    else:
        train_symbol(args.symbol, args.model)
