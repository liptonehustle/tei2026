"""
execution_engine/scheduler.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 7 + 9 — Execution Scheduler

Orchestrates the full automated trading pipeline:
  - Every 1 min:  monitor open positions (SL/TP check)
  - Every 5 min:  run decision engine + execute signals
  - Every 6 hours: check if retraining is needed

Run: python -m execution_engine.scheduler
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import signal
sys.path.insert(0, ".")

from datetime import datetime, timezone
from loguru import logger
from apscheduler.schedulers.blocking import BlockingScheduler

from execution_engine.executor import get_exchange, get_account_balance, execute_decision
from execution_engine.monitor import check_positions
from execution_engine.risk_manager import log_status
from decision_engine.engine import run_all
from decision_engine.ollama_client import is_available
from ml_models.retrainer import run_retrainer
from database.db import test_connection
from notifications.telegram import alert_daily_summary
from strategies.runner import check_virtual_sl_tp

import os
os.makedirs("logs", exist_ok=True)
logger.add("logs/execution.log", rotation="10 MB", retention="30 days")

scheduler = BlockingScheduler(timezone="UTC")


def monitor_job():
    """Every 1 minute — check SL/TP on open positions."""
    try:
        exchange = get_exchange()
        closed   = check_positions(exchange)
        # Check virtual SL/TP for all strategies every minute
        for _symbol in ["BTC/USDT", "ETH/USDT", "BNB/USDT"]:
            try:
                check_virtual_sl_tp(_symbol)
            except Exception as e:
                logger.error(f"Virtual SL/TP check failed [{_symbol}]: {e}")
        if closed:
            wins   = [t for t in closed if t["pnl"] > 0]
            losses = [t for t in closed if t["pnl"] <= 0]
            logger.info(f"Monitor: closed {len(closed)} positions | {len(wins)} wins {len(losses)} losses")
    except Exception as e:
        logger.error(f"Monitor job crashed: {e}")


def decision_and_execute_job():
    """Every 5 minutes — get decisions and execute actionable ones."""
    try:
        logger.info("=" * 55)
        logger.info(f"Execution cycle — {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
        logger.info("=" * 55)

        decisions = run_all()
        # Check virtual SL/TP using candle high/low
        for _symbol in ["BTC/USDT", "ETH/USDT", "BNB/USDT"]:
            try:
                check_virtual_sl_tp(_symbol)
            except Exception as e:
                logger.error(f"Virtual SL/TP check failed [{_symbol}]: {e}")

        executed = 0
        for d in decisions:
            if d and d.get("action") in ("buy", "sell"):
                result = execute_decision(d)
                if result:
                    executed += 1

        logger.info(f"Cycle complete: {len(decisions)} decisions | {executed} orders placed")

        balance = get_account_balance()
        log_status(balance)

    except Exception as e:
        logger.error(f"Decision/execute job crashed: {e}")


def retrainer_job():
    """Every 6 hours — check if model retraining is needed."""
    try:
        logger.info("=" * 55)
        logger.info(f"Retrainer check — {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC")
        logger.info("=" * 55)
        run_retrainer()
    except Exception as e:
        logger.error(f"Retrainer job crashed: {e}")

def daily_summary_job():
    """Daily at 13:00 UTC (20:00 WIB) — send Telegram daily summary."""
    try:
        logger.info("Sending daily summary to Telegram...")
        alert_daily_summary()
    except Exception as e:
        logger.error(f"Daily summary job crashed: {e}")

def shutdown(signum, frame):
    logger.info("Shutdown signal — stopping execution engine...")
    scheduler.shutdown(wait=False)
    sys.exit(0)


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Execution Engine — Phase 7 + 9 (PAPER TRADING)")
    logger.info("=" * 55)

    if not test_connection():
        logger.error("PostgreSQL not reachable.")
        sys.exit(1)

    if not is_available():
        logger.error("Ollama not available.")
        sys.exit(1)

    try:
        balance = get_account_balance()
        logger.success(f"Paper trading ready | Balance: {balance:.2f} USDT (simulated)")
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        sys.exit(1)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Schedule jobs
    scheduler.add_job(monitor_job,              "interval", minutes=1,  id="monitor",   max_instances=1)
    scheduler.add_job(decision_and_execute_job, "interval", minutes=5,  id="execute",   max_instances=1)
    scheduler.add_job(retrainer_job,            "interval", hours=6,    id="retrainer", max_instances=1)
    scheduler.add_job(daily_summary_job, "cron", hour=13, minute=0, id="daily_summary", max_instances=1)

    logger.info("Scheduler started:")
    logger.info("  - Position monitor:    every 1 minute")
    logger.info("  - Decision + execute:  every 5 minutes")
    logger.info("  - Model retrainer:     every 6 hours")
    logger.info("  - Daily summary:       13:00 UTC (20:00 WIB)")
    logger.warning("⚠️  Running in PAPER TRADING mode — no real money at risk")

    # Run immediately on start
    decision_and_execute_job()

    scheduler.start()