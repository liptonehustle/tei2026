"""
database/monitor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 3 — Database Monitor

Shows a live summary of the database state.
Run anytime to check pipeline health.

Usage: python -m database.monitor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

from datetime import datetime, timezone
from loguru import logger
from database.db import DB


def print_table_stats():
    sql = """
        SELECT
            relname                            AS table_name,
            n_live_tup                         AS row_count,
            pg_size_pretty(pg_total_relation_size(relid)) AS total_size
        FROM pg_stat_user_tables
        ORDER BY n_live_tup DESC;
    """
    with DB() as (_, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    logger.info("── Table stats ─────────────────────────────────")
    for table, count, size in rows:
        logger.info(f"  {table:<20} {count:>10,} rows  {size:>10}")


def print_market_data_summary():
    sql = """
        SELECT
            symbol,
            COUNT(*)                    AS candles,
            MIN(timestamp)              AS oldest,
            MAX(timestamp)              AS newest,
            MAX(close)                  AS high_price,
            MIN(close)                  AS low_price
        FROM market_data
        GROUP BY symbol
        ORDER BY symbol;
    """
    with DB() as (_, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    logger.info("── Market data summary ─────────────────────────")
    for symbol, candles, oldest, newest, high, low in rows:
        age = datetime.now(timezone.utc) - newest.replace(tzinfo=timezone.utc)
        logger.info(
            f"  {symbol:<12} | {candles:>8,} candles "
            f"| high={float(high):>12,.2f} low={float(low):>12,.2f} "
            f"| latest: {int(age.total_seconds())}s ago"
        )


def print_indicators_summary():
    sql = """
        SELECT symbol, COUNT(*) as rows, MAX(timestamp) as latest
        FROM indicators
        GROUP BY symbol
        ORDER BY symbol;
    """
    with DB() as (_, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    logger.info("── Indicators summary ──────────────────────────")
    if not rows:
        logger.warning("  No indicators yet — run Phase 4 indicator engine first")
        return
    for symbol, count, latest in rows:
        age = datetime.now(timezone.utc) - latest.replace(tzinfo=timezone.utc)
        logger.info(f"  {symbol:<12} | {count:>8,} rows | latest: {int(age.total_seconds())}s ago")


def print_predictions_summary():
    sql = """
        SELECT symbol, model_version, COUNT(*) as rows, MAX(timestamp) as latest
        FROM predictions
        GROUP BY symbol, model_version
        ORDER BY symbol, model_version;
    """
    with DB() as (_, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    logger.info("── Predictions summary ─────────────────────────")
    if not rows:
        logger.warning("  No predictions yet — run Phase 5 ML model first")
        return
    for symbol, model, count, latest in rows:
        logger.info(f"  {symbol:<12} [{model}] | {count:>6,} predictions")


def print_trades_summary():
    sql = """
        SELECT
            status,
            COUNT(*)                        AS count,
            COALESCE(SUM(profit_loss), 0)   AS total_pnl
        FROM trades
        GROUP BY status;
    """
    with DB() as (_, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    logger.info("── Trades summary ──────────────────────────────")
    if not rows:
        logger.info("  No trades yet")
        return
    for status, count, pnl in rows:
        logger.info(f"  {status:<10} | {count:>4} trades | P&L: {float(pnl):>+10.4f}")


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Database Monitor — TEI2026 Trading Platform")
    logger.info(f"Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")
    logger.info("=" * 55)

    try:
        print_table_stats()
        print_market_data_summary()
        print_indicators_summary()
        print_predictions_summary()
        print_trades_summary()
        logger.info("=" * 55)
    except Exception as e:
        logger.error(f"Monitor failed: {e}")