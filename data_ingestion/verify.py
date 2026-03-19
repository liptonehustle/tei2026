"""
data_ingestion/verify.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 2 verification — run after collector to confirm data is flowing.

Checks:
  1. Row count in market_data per symbol
  2. Latest candle timestamp (detects stale data)
  3. Redis queue depth
  4. Detects gaps in time series

Usage: python -m data_ingestion.verify
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
from datetime import datetime, timezone, timedelta

from loguru import logger

sys.path.insert(0, ".")
from database.db import DB
from data_ingestion.collector import get_redis, SYMBOLS, TIMEFRAME


def check_row_counts():
    logger.info("── Row counts ──────────────────────────────────")
    sql = """
        SELECT symbol, timeframe, COUNT(*) as rows,
               MIN(timestamp) as oldest,
               MAX(timestamp) as newest
        FROM market_data
        GROUP BY symbol, timeframe
        ORDER BY symbol, timeframe;
    """
    with DB() as (_, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    if not rows:
        logger.warning("market_data table is EMPTY — run the collector first")
        return False

    for symbol, tf, count, oldest, newest in rows:
        age = datetime.now(timezone.utc) - newest.replace(tzinfo=timezone.utc)
        age_str = f"{int(age.total_seconds() / 60)} min ago"
        logger.info(f"  {symbol} [{tf}] | {count:,} rows | latest: {age_str}")

    return True


def check_gaps():
    logger.info("── Gap check (last 60 candles) ─────────────────")
    sql = """
        SELECT symbol,
               COUNT(*) as candles,
               EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) / 60 as span_minutes
        FROM (
            SELECT symbol, timestamp
            FROM market_data
            WHERE timeframe = %s
            ORDER BY timestamp DESC
            LIMIT 60
        ) sub
        GROUP BY symbol;
    """
    with DB() as (_, cur):
        cur.execute(sql, (TIMEFRAME,))
        rows = cur.fetchall()

    all_ok = True
    for symbol, candles, span in rows:
        expected = candles - 1
        actual   = int(span) if span else 0
        if abs(actual - expected) > 2:
            logger.warning(f"  ⚠️  {symbol} | possible gap — {actual} min span for {candles} candles (expected ~{expected})")
            all_ok = False
        else:
            logger.info(f"  ✅ {symbol} | no gaps detected in last {candles} candles")
    return all_ok


def check_redis_queue():
    logger.info("── Redis queue ─────────────────────────────────")
    try:
        r = get_redis()
        depth = r.llen("raw:market_data")
        logger.info(f"  raw:market_data queue depth: {depth} items")
        if depth == 0:
            logger.warning("  Queue is empty — collector may not be running yet (OK if just started)")
        elif depth > 500:
            logger.warning(f"  Queue depth {depth} is high — indicator engine may be behind")
        else:
            logger.info("  ✅ Queue depth OK")
        return True
    except Exception as e:
        logger.error(f"  Redis check failed: {e}")
        return False


def check_freshness():
    logger.info("── Freshness check ─────────────────────────────")
    sql = """
        SELECT symbol, MAX(timestamp) as latest
        FROM market_data
        WHERE timeframe = %s
        GROUP BY symbol;
    """
    with DB() as (_, cur):
        cur.execute(sql, (TIMEFRAME,))
        rows = cur.fetchall()

    stale_threshold = timedelta(minutes=3)
    all_fresh = True
    for symbol, latest in rows:
        age = datetime.now(timezone.utc) - latest.replace(tzinfo=timezone.utc)
        if age > stale_threshold:
            logger.warning(f"  ⚠️  {symbol} | STALE — last candle was {int(age.total_seconds()/60)} min ago")
            all_fresh = False
        else:
            logger.info(f"  ✅ {symbol} | fresh ({int(age.total_seconds())}s ago)")
    return all_fresh


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Phase 2 — Data Collector Verification")
    logger.info("=" * 55)

    results = {
        "Row counts":  check_row_counts(),
        "Gaps":        check_gaps(),
        "Redis queue": check_redis_queue(),
        "Freshness":   check_freshness(),
    }

    logger.info("=" * 55)
    if all(results.values()):
        logger.success("Phase 2 verification PASSED — data is flowing correctly.")
        logger.success("Ready to proceed to Phase 3 (Database Pipeline).")
    else:
        failed = [k for k, v in results.items() if not v]
        logger.warning(f"Some checks need attention: {failed}")
        logger.info("This may be normal if the collector just started. Re-run in 2 minutes.")
