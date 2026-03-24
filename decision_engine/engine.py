"""
decision_engine/engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 6 — AI Decision Engine

Combines:
  1. ML prediction (RandomForest prob_up/prob_down)
  2. Latest technical indicators
  3. Ollama LLM reasoning
  4. Risk context (open trades, daily P&L)

Outputs a structured trade decision saved to DB.

Run modes:
  One shot:  python -m decision_engine.engine --symbol BTC/USDT
  All:       python -m decision_engine.engine --symbol all
  Scheduler: python -m decision_engine.engine --mode scheduler
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse
import os
import sys
import signal
from datetime import datetime, timezone

sys.path.insert(0, ".")

from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from decision_engine.ollama_client import is_available, ask_json
from decision_engine.prompt_builder import build_decision_prompt, SYSTEM_PROMPT
from ml_models.predictor import predict_latest
from database.queries import (
    get_indicators, get_latest_candle,
    get_open_trades, get_daily_pnl,
    save_trade_decision,
)
from database.db import test_connection
from strategies.runner import run_strategies

os.makedirs("logs", exist_ok=True)
logger.add("logs/decision_engine.log", rotation="10 MB", retention="7 days")

SYMBOLS        = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAME      = "5m"
ACCOUNT_CAPITAL = 10_000.0  # update this to your actual capital
VIRTUAL_QUANTITY = 1.0  # virtual position size for strategy P&L tracking

# ══════════════════════════════════════════════════════
# VALIDATION
# ══════════════════════════════════════════════════════

def validate_decision(decision: dict, current_price: float) -> dict | None:
    """
    Validate and sanitize Ollama's JSON output.
    Returns cleaned decision or None if invalid.
    """
    if not isinstance(decision, dict):
        logger.error("Decision is not a dict")
        return None

    action = decision.get("action", "").lower()
    if action not in ("buy", "sell", "hold"):
        logger.error(f"Invalid action: {action}")
        return None

    confidence = float(decision.get("confidence", 0))
    if not 0 <= confidence <= 1:
        confidence = max(0.0, min(1.0, confidence))

    # Compute SL/TP from current price if not provided or invalid
    if action == "buy":
        entry   = float(decision.get("entry_price") or current_price)
        sl      = float(decision.get("stop_loss")   or entry * 0.992)
        tp      = float(decision.get("take_profit") or entry * 1.020)
    elif action == "sell":
        entry   = float(decision.get("entry_price") or current_price)
        sl      = float(decision.get("stop_loss")   or entry * 1.008)
        tp      = float(decision.get("take_profit") or entry * 0.980)
    else:  # hold
        entry = sl = tp = None

    return {
        "action":      action,
        "entry_price": entry,
        "stop_loss":   sl,
        "take_profit": tp,
        "confidence":  round(confidence, 4),
        "reasoning":   str(decision.get("reasoning", ""))[:500],
    }


# ══════════════════════════════════════════════════════
# MAIN DECISION FUNCTION
# ══════════════════════════════════════════════════════

def make_decision(symbol: str) -> dict | None:
    """
    Full decision pipeline for one symbol.

    Steps:
      1. Get latest ML prediction
      2. Get latest indicators
      3. Get risk context
      4. Build prompt → send to Ollama
      5. Validate response
      6. Save to DB

    Returns decision dict or None if any step fails.
    """
    logger.info(f"─── Decision: {symbol} ───────────────────────────")

    # 1. ML Prediction
    prediction = predict_latest(symbol, model_type="rf")
    if not prediction:
        logger.error(f"[{symbol}] No ML prediction available")
        return None

    # 2. Latest indicators
    indicators_df = get_indicators(symbol, timeframe=TIMEFRAME, limit=1)
    if indicators_df.empty:
        logger.error(f"[{symbol}] No indicators available")
        return None
    indicators = indicators_df.iloc[-1].to_dict()

    # 3. Latest price
    candle = get_latest_candle(symbol, timeframe=TIMEFRAME)
    if not candle:
        logger.error(f"[{symbol}] No candle data available")
        return None
    current_price = float(candle["close"])

    # 4. Risk context
    open_trades = get_open_trades()
    open_count  = len([t for t in open_trades if t["symbol"] == symbol])
    daily_pnl   = get_daily_pnl()

    # 5. Run all strategies — get strongest signal
    strategy_signal = run_strategies(
        symbol        = symbol,
        indicators    = indicators,
        prediction    = prediction,
        current_price = current_price,
        quantity      = VIRTUAL_QUANTITY,
    )

    # 5b. Build prompt — inject strategy signal as context
    prompt = build_decision_prompt(
        symbol          = symbol,
        current_price   = current_price,
        indicators      = indicators,
        prediction      = prediction,
        open_trades     = open_count,
        daily_pnl       = daily_pnl,
        account_capital = ACCOUNT_CAPITAL,
        strategy_signal = strategy_signal,
    )

    raw_decision = ask_json(prompt, system=SYSTEM_PROMPT)
    if not raw_decision:
        if strategy_signal and strategy_signal.action != "hold" and strategy_signal.confidence >= 0.70:
            logger.warning(f"[{symbol}] Ollama failed — falling back to strategy signal: {strategy_signal.strategy_name} {strategy_signal.action.upper()} conf={strategy_signal.confidence:.0%}")
            raw_decision = {
                "action":      strategy_signal.action,
                "entry_price": strategy_signal.entry_price,
                "stop_loss":   strategy_signal.stop_loss,
                "take_profit": strategy_signal.take_profit,
                "confidence":  strategy_signal.confidence,
                "reasoning":   f"[fallback] {strategy_signal.strategy_name}: {strategy_signal.reasoning}",
            }
        else:
            logger.error(f"[{symbol}] Ollama failed and no strong strategy signal — skipping")
            return None

    # 6. Validate
    decision = validate_decision(raw_decision, current_price)
    if not decision:
        logger.error(f"[{symbol}] Decision validation failed")
        return None

    # 6b. If Ollama says HOLD but strategy has strong signal, trust strategy
    if decision["action"] == "hold" and strategy_signal and strategy_signal.confidence >= 0.70:
        logger.info(f"[{symbol}] Ollama HOLD overridden by strategy {strategy_signal.strategy_name} conf={strategy_signal.confidence:.0%}")
        decision["action"]      = strategy_signal.action
        decision["entry_price"] = strategy_signal.entry_price
        decision["stop_loss"]   = strategy_signal.stop_loss
        decision["take_profit"] = strategy_signal.take_profit
        decision["confidence"]  = strategy_signal.confidence
        decision["reasoning"]   = f"[{strategy_signal.strategy_name}] {strategy_signal.reasoning}"

    # 7. Log decision
    action = decision["action"].upper()
    emoji  = "🟢" if action == "BUY" else "🔴" if action == "SELL" else "🟡"
    logger.info(
        f"{emoji} {symbol} → {action} | "
        f"confidence={decision['confidence']:.0%} | "
        f"prob_up={prediction['prob_up']:.0%} | "
        f"{decision['reasoning']}"
    )

    # 8. Save to DB
    db_record = {
        "timestamp":    datetime.now(timezone.utc),
        "symbol":       symbol,
        "action":       decision["action"],
        "entry_price":  decision["entry_price"],
        "stop_loss":    decision["stop_loss"],
        "take_profit":  decision["take_profit"],
        "confidence":   decision["confidence"],
        "reasoning":    decision["reasoning"],
        "prediction_id": prediction.get("prediction_id"),
    }
    decision_id = save_trade_decision(db_record)
    decision["decision_id"] = decision_id
    decision["symbol"]      = symbol

    return decision


def run_all() -> list[dict]:
    """Run decision engine for all configured symbols."""
    decisions = []
    for symbol in SYMBOLS:
        try:
            d = make_decision(symbol)
            if d:
                decisions.append(d)
        except Exception as e:
            logger.error(f"[{symbol}] Decision engine crashed: {e}")
    return decisions


# ══════════════════════════════════════════════════════
# SCHEDULER
# ══════════════════════════════════════════════════════

def run_scheduler():
    """Run decision engine every 5 minutes."""
    scheduler = BlockingScheduler(timezone="UTC")

    def job():
        logger.info("=" * 55)
        logger.info(f"Decision Engine run — {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
        logger.info("=" * 55)
        decisions = run_all()
        actionable = [d for d in decisions if d["action"] != "hold"]
        logger.info(f"Decisions: {len(decisions)} total | {len(actionable)} actionable")

    scheduler.add_job(job, "interval", minutes=5, id="decision_engine", max_instances=1)

    def shutdown(signum, frame):
        logger.info("Shutting down decision engine...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Decision Engine scheduler started — running every 5 minutes")
    job()  # run immediately on start
    scheduler.start()


# ══════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Decision Engine — Phase 6")
    parser.add_argument("--symbol", default="all", help="Symbol or 'all'")
    parser.add_argument("--mode",   default="once", choices=["once", "scheduler"])
    args = parser.parse_args()

    if not test_connection():
        logger.error("PostgreSQL not reachable.")
        sys.exit(1)

    if not is_available():
        logger.error("Ollama not available. Run: ollama pull llama3")
        sys.exit(1)

    if args.mode == "scheduler":
        run_scheduler()
    else:
        if args.symbol == "all":
            decisions = run_all()
        else:
            decisions = [make_decision(args.symbol)]

        logger.info("=" * 55)
        for d in decisions:
            if d:
                logger.info(
                    f"  {d['symbol']:<12} → {d['action'].upper():<4} "
                    f"| confidence={d['confidence']:.0%}"
                )
