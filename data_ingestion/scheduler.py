"""
data_ingestion/scheduler.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs the data collector on a fixed schedule using APScheduler.

Run:  python -m data_ingestion.scheduler
      (keep this running in background or as a Docker service)

Jobs:
  - collect_market_data  → every 1 minute
  - health_check         → every 5 minutes (logs queue depth)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import time
import signal

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from loguru import logger
from utils.warp import ensure_connected

sys.path.insert(0, ".")
from data_ingestion.collector import run_once, get_redis, SYMBOLS
from database.db import test_connection

# ── Scheduler setup ────────────────────────────────────────────────────────

scheduler = BlockingScheduler(timezone="UTC")


def collect_job():
    """Scheduled job: collect one round of market data."""
    try:
        run_once()
        ensure_connected()
    except Exception as e:
        logger.error(f"Collection job crashed: {e}")


def health_check_job():
    """Scheduled job: log queue depth every 5 minutes."""
    try:
        r = get_redis()
        depth = r.llen("raw:market_data")
        logger.info(f"[Health] Redis queue depth: {depth} items | symbols: {len(SYMBOLS)}")
        if depth > 500:
            logger.warning(f"[Health] Queue depth {depth} is high — indicator engine may be lagging")
    except Exception as e:
        logger.error(f"[Health] Health check failed: {e}")


def on_job_event(event):
    """Log APScheduler job errors."""
    if event.exception:
        logger.error(f"Job {event.job_id} raised: {event.exception}")


def shutdown(signum, frame):
    logger.info("Shutdown signal received — stopping scheduler...")
    scheduler.shutdown(wait=False)
    sys.exit(0)


# ── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Data Collector Scheduler — Phase 2")
    logger.info("=" * 55)

    if not test_connection():
        logger.error("PostgreSQL not reachable. Exiting.")
        sys.exit(1)

    # Graceful shutdown on Ctrl+C or SIGTERM (Docker stop)
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Register APScheduler event listener
    scheduler.add_listener(on_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

    # Jobs
    scheduler.add_job(collect_job,      "interval", minutes=1,  id="collect_market_data", max_instances=1)
    scheduler.add_job(health_check_job, "interval", minutes=5,  id="health_check",         max_instances=1)

    logger.info("Scheduler started. Collecting every 1 minute. Press Ctrl+C to stop.")
    logger.info(f"Watching symbols: {SYMBOLS}")

    # Run one collection immediately on startup, then hand off to scheduler
    logger.info("Running initial collection now...")
    ensure_connected()
    collect_job()

    scheduler.start()
