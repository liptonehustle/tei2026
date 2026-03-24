"""
ml_models/retrainer.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 9 — Automated Model Retraining

Triggers:
  1. Scheduled: every 3 days
  2. Performance drop: win rate < WIN_RATE_THRESHOLD
  3. Rollback: if new model worse than old, revert

Run standalone: python -m ml_models.retrainer
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from loguru import logger

from ml_models.trainer import (
    train_symbol, get_latest_version, load_model, SAVED_DIR, SYMBOLS
)
from database.db import DB

os.makedirs("logs", exist_ok=True)
logger.add("logs/retrainer.log", rotation="10 MB", retention="30 days")

# ── Config ─────────────────────────────────────────────
WIN_RATE_THRESHOLD   = 0.45   # retrain if win rate drops below 45%
MIN_TRADES_TO_EVAL   = 10     # need at least 10 closed trades to evaluate
RETRAIN_INTERVAL_DAYS = 3     # scheduled retrain every 3 days
MODEL_TYPE           = "rf"   # default model type to retrain
RETRAINER_STATE_FILE = Path("ml_models/saved/retrainer_state.json")


# ── State management ───────────────────────────────────

def load_state() -> dict:
    """Load retrainer state (last retrain time, etc.)"""
    if RETRAINER_STATE_FILE.exists():
        with open(RETRAINER_STATE_FILE) as f:
            return json.load(f)
    return {
        "last_retrain": None,
        "retrain_count": 0,
        "last_trigger": None,
    }


def save_state(state: dict):
    with open(RETRAINER_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Performance evaluation ─────────────────────────────

def get_recent_win_rate(days: int = 3) -> float | None:
    """
    Calculate win rate from closed trades in the last N days.
    Returns None if not enough data.
    """
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        with DB() as (conn, cur):
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END) AS wins
                FROM trades
                WHERE status = 'closed'
                  AND closed_at >= %s
            """, (since,))
            row = cur.fetchone()

        total, wins = row
        if not total or total < MIN_TRADES_TO_EVAL:
            logger.info(f"  Not enough trades to evaluate ({total or 0} < {MIN_TRADES_TO_EVAL})")
            return None

        win_rate = float(wins) / float(total)
        logger.info(f"  Recent win rate ({days}d): {win_rate:.1%} ({wins}/{total} trades)")
        return win_rate

    except Exception as e:
        logger.error(f"Could not calculate win rate: {e}")
        return None


def get_model_metrics(symbol: str, model_type: str = MODEL_TYPE) -> dict | None:
    """Load metrics from the current saved model."""
    version = get_latest_version(symbol, model_type)
    if not version:
        return None
    try:
        _, _, meta = load_model(version)
        return meta.get("metrics", {})
    except Exception as e:
        logger.error(f"Could not load model metrics for {symbol}: {e}")
        return None


# ── Retrain logic ──────────────────────────────────────

def should_retrain_scheduled(state: dict) -> bool:
    """Check if scheduled retrain interval has passed."""
    last = state.get("last_retrain")
    if not last:
        logger.info("  No previous retrain — scheduled retrain needed")
        return True

    last_dt   = datetime.fromisoformat(last)
    days_since = (datetime.now(timezone.utc) - last_dt).days
    if days_since >= RETRAIN_INTERVAL_DAYS:
        logger.info(f"  {days_since} days since last retrain (interval={RETRAIN_INTERVAL_DAYS}d) — scheduled retrain needed")
        return True

    logger.info(f"  {days_since} days since last retrain — not due yet")
    return False


def should_retrain_performance() -> bool:
    """Check if win rate has dropped below threshold."""
    win_rate = get_recent_win_rate(days=3)
    if win_rate is None:
        return False

    if win_rate < WIN_RATE_THRESHOLD:
        logger.warning(
            f"  ⚠️  Win rate {win_rate:.1%} below threshold {WIN_RATE_THRESHOLD:.1%} "
            f"— performance retrain triggered"
        )
        return True

    logger.info(f"  Win rate {win_rate:.1%} OK (threshold={WIN_RATE_THRESHOLD:.1%})")
    return False


def compare_models(old_version: str, new_version: str) -> bool:
    """
    Compare new vs old model metrics.
    Returns True if new model is better or equal.
    """
    try:
        _, _, old_meta = load_model(old_version)
        _, _, new_meta = load_model(new_version)

        old_auc = old_meta["metrics"].get("roc_auc", 0)
        new_auc = new_meta["metrics"].get("roc_auc", 0)
        old_f1  = old_meta["metrics"].get("f1", 0)
        new_f1  = new_meta["metrics"].get("f1", 0)

        logger.info(f"  Old model: AUC={old_auc:.4f} F1={old_f1:.4f} [{old_version}]")
        logger.info(f"  New model: AUC={new_auc:.4f} F1={new_f1:.4f} [{new_version}]")

        # New model must be at least as good (within 1% tolerance)
        auc_ok = new_auc >= (old_auc - 0.01)
        f1_ok  = new_f1  >= (old_f1  - 0.01)

        if auc_ok and f1_ok:
            logger.success(f"  ✅ New model passes — keeping [{new_version}]")
            return True
        else:
            logger.warning(f"  ❌ New model worse — rolling back to [{old_version}]")
            return False

    except Exception as e:
        logger.error(f"Model comparison failed: {e} — keeping new model")
        return True


def rollback_model(symbol: str, bad_version: str, model_type: str = MODEL_TYPE):
    """Delete the bad model files so the previous version is used."""
    try:
        for suffix in [".joblib", "_scaler.joblib", "_meta.json"]:
            f = SAVED_DIR / f"{bad_version}{suffix}"
            if f.exists():
                f.unlink()
                logger.info(f"  Removed: {f.name}")
        logger.info(f"  Rolled back — previous model will be used for {symbol}")
    except Exception as e:
        logger.error(f"Rollback failed: {e}")


def retrain_symbol(symbol: str, trigger: str) -> bool:
    """
    Retrain a single symbol with rollback protection.
    Returns True if new model was kept, False if rolled back.
    """
    logger.info(f"── Retraining {symbol} [trigger={trigger}] ──────────")

    # Save current version before retraining
    old_version = get_latest_version(symbol, MODEL_TYPE)

    # Run training
    try:
        versions = train_symbol(symbol, MODEL_TYPE)
        new_version = versions.get(MODEL_TYPE)
        if not new_version:
            logger.error(f"Training failed for {symbol}")
            return False
    except Exception as e:
        logger.error(f"Training crashed for {symbol}: {e}")
        return False

    # Compare models if we had a previous version
    if old_version and old_version != new_version:
        is_better = compare_models(old_version, new_version)
        if not is_better:
            rollback_model(symbol, new_version)
            return False

    logger.success(f"✅ {symbol} retrained successfully → {new_version}")
    return True


# ── Main entry point ───────────────────────────────────

def run_retrainer():
    """
    Main retrainer logic — checks triggers and retrains if needed.
    Called by scheduler every few hours.
    """
    logger.info("=" * 55)
    logger.info(f"Retrainer check — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    logger.info("=" * 55)

    state   = load_state()
    trigger = None

    # Check triggers
    perf_drop = should_retrain_performance()
    scheduled = should_retrain_scheduled(state)

    if perf_drop:
        trigger = "performance_drop"
    elif scheduled:
        trigger = "scheduled"
    else:
        logger.info("No retrain needed — all good ✅")
        return

    # Retrain all symbols
    logger.info(f"Trigger: {trigger} — retraining all symbols")
    results = {}
    for symbol in SYMBOLS:
        results[symbol] = retrain_symbol(symbol, trigger)

    # Update state
    state["last_retrain"]  = datetime.now(timezone.utc).isoformat()
    state["last_trigger"]  = trigger
    state["retrain_count"] = state.get("retrain_count", 0) + 1
    save_state(state)

    # Summary
    success = sum(results.values())
    logger.info("=" * 55)
    logger.info(f"Retrain complete: {success}/{len(SYMBOLS)} symbols updated")
    for symbol, ok in results.items():
        logger.info(f"  {'✅' if ok else '❌'} {symbol}")


if __name__ == "__main__":
    from database.db import test_connection
    if not test_connection():
        logger.error("PostgreSQL not reachable.")
        sys.exit(1)
    run_retrainer()