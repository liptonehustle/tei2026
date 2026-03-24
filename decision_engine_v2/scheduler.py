"""
decision_engine/scheduler.py
Jalankan decision engine setiap 5 menit via APScheduler.
Offset +90 detik dari data_ingestion/scheduler.py agar data sudah masuk DB.

Run:
    python -m decision_engine.scheduler
"""

import logging
import time
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from decision_engine.engine import run_decision_cycle

logging.basicConfig(
    level   = logging.INFO,
    format  = "%(asctime)s [%(levelname)s] %(name)s -- %(message)s",
    datefmt = "%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("decision_scheduler")


def job_run_decision():
    log.info("Running decision cycle START")
    t0 = time.time()
    try:
        results = run_decision_cycle()
        elapsed = round(time.time() - t0, 2)
        log.info(f"Decision cycle DONE in {elapsed}s")
        for r in results:
            if r.get("status") == "ok":
                log.info(
                    f"  {r['symbol']}: action={r['action']}, "
                    f"score={r.get('combined_score', 0):.3f}, "
                    f"risk={'OK' if r.get('risk_ok') else 'BLOCKED'}"
                )
            else:
                log.warning(f"  {r['symbol']}: {r.get('status')}")
    except Exception as e:
        log.error(f"Decision cycle ERROR: {e}", exc_info=True)


def main():
    scheduler = BlockingScheduler(timezone="UTC")

    # Setiap 5 menit, detik ke-30 menit ke-1
    # Trigger: xx:01:30, xx:06:30, xx:11:30 dst
    scheduler.add_job(
        func          = job_run_decision,
        trigger       = CronTrigger(minute="1,6,11,16,21,26,31,36,41,46,51,56", second=30),
        id            = "decision_cycle",
        name          = "AI Decision Engine (5m)",
        max_instances = 1,
        coalesce      = True,
    )

    log.info("=" * 55)
    log.info("  TEI2026 -- Decision Engine Scheduler")
    log.info("  Interval : every 5 minutes (offset +90s from collector)")
    log.info("  Model    : llama3 via Ollama")
    log.info("  Symbols  : BTCUSDT, ETHUSDT, BNBUSDT")
    log.info("=" * 55)

    log.info("Running initial decision cycle on startup...")
    job_run_decision()

    log.info("Scheduler started. Press Ctrl+C to stop.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
