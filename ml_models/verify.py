"""
ml_models/verify.py
Phase 5 verification — confirm models trained and predictions work.

Usage: python -m ml_models.verify
"""

import sys
sys.path.insert(0, ".")

from pathlib import Path
import json
from loguru import logger
from ml_models.trainer import get_latest_version, load_model, SAVED_DIR
from ml_models.predictor import predict_latest

SYMBOLS    = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
MODEL_TYPE = "rf"


def check_saved_models():
    logger.info("── Saved models ────────────────────────────────")
    found = 0
    for symbol in SYMBOLS:
        version = get_latest_version(symbol, MODEL_TYPE)
        if not version:
            logger.warning(f"  ⚠️  {symbol} — no model found")
            continue

        meta_path = SAVED_DIR / f"{version}_meta.json"
        with open(meta_path) as f:
            meta = json.load(f)

        m = meta["metrics"]
        logger.info(
            f"  ✅ {symbol:<12} | {version} "
            f"| AUC={m['roc_auc']:.4f} F1={m['f1']:.4f} Acc={m['accuracy']:.4f}"
        )
        found += 1
    return found == len(SYMBOLS)


def check_predictions():
    logger.info("── Live predictions ────────────────────────────")
    ok = True
    for symbol in SYMBOLS:
        pred = predict_latest(symbol, MODEL_TYPE)
        if not pred:
            logger.error(f"  ❌ {symbol} — prediction failed")
            ok = False
            continue

        signal = "🟢 UP  " if pred["prob_up"] > 0.55 else \
                 "🔴 DOWN" if pred["prob_down"] > 0.55 else \
                 "🟡 HOLD"
        logger.info(
            f"  {signal} {symbol:<12} "
            f"| prob_up={pred['prob_up']:.2%} "
            f"| prob_down={pred['prob_down']:.2%}"
        )
    return ok


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Phase 5 — ML Model Verification")
    logger.info("=" * 55)

    results = {
        "Saved models":    check_saved_models(),
        "Live predictions": check_predictions(),
    }

    logger.info("=" * 55)
    if all(results.values()):
        logger.success("Phase 5 PASSED — ML models ready for decision engine.")
        logger.success("Ready to proceed to Phase 5.5 (Backtesting).")
    else:
        failed = [k for k, v in results.items() if not v]
        logger.error(f"Issues: {failed}")
