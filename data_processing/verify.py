"""
data_processing/verify.py
Phase 4 verification — confirm indicators are computed correctly.

Usage: python -m data_processing.verify
"""

import sys
sys.path.insert(0, ".")

from loguru import logger
from database.queries import get_indicators, get_candles
from database.db import DB

SYMBOLS   = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAME = "5m"


def check_indicator_counts():
    logger.info("── Indicator row counts ────────────────────────")
    sql = """
        SELECT symbol, COUNT(*) as rows,
               MIN(timestamp) as oldest,
               MAX(timestamp) as newest
        FROM indicators
        WHERE timeframe = %s
        GROUP BY symbol ORDER BY symbol;
    """
    with DB() as (_, cur):
        cur.execute(sql, (TIMEFRAME,))
        rows = cur.fetchall()

    if not rows:
        logger.error("  No indicators found — run backfill first")
        return False

    for symbol, count, oldest, newest in rows:
        logger.info(f"  {symbol:<12} | {count:>8,} rows | {oldest.date()} → {newest.date()}")
    return True


def check_indicator_values():
    logger.info("── Latest indicator values ─────────────────────")
    ok = True
    for symbol in SYMBOLS:
        df = get_indicators(symbol, TIMEFRAME, limit=1)
        if df.empty:
            logger.warning(f"  {symbol} — no indicators")
            ok = False
            continue

        row = df.iloc[-1]
        # Sanity checks
        rsi_ok  = 0 < float(row["rsi_14"]) < 100
        ema_ok  = float(row["ema_20"]) > 0
        adx_ok  = 0 < float(row["adx"]) < 100

        status = "✅" if (rsi_ok and ema_ok and adx_ok) else "⚠️ "
        logger.info(
            f"  {status} {symbol:<12} | "
            f"EMA20={float(row['ema_20']):>10,.2f} "
            f"RSI={float(row['rsi_14']):>5.1f} "
            f"MACD={float(row['macd']):>8.4f} "
            f"ADX={float(row['adx']):>5.1f}"
        )
        if not (rsi_ok and ema_ok and adx_ok):
            ok = False
    return ok


def check_coverage():
    logger.info("── Coverage (indicators vs candles) ────────────")
    sql = """
        SELECT
            m.symbol,
            COUNT(DISTINCT m.timestamp) AS candles,
            COUNT(DISTINCT i.timestamp) AS indicators,
            ROUND(COUNT(DISTINCT i.timestamp) * 100.0 /
                  NULLIF(COUNT(DISTINCT m.timestamp), 0), 1) AS coverage_pct
        FROM market_data m
        LEFT JOIN indicators i
            ON m.symbol = i.symbol AND m.timestamp = i.timestamp
        WHERE m.timeframe = %s
        GROUP BY m.symbol
        ORDER BY m.symbol;
    """
    with DB() as (_, cur):
        cur.execute(sql, (TIMEFRAME,))
        rows = cur.fetchall()

    ok = True
    for symbol, candles, indicators, pct in rows:
        status = "✅" if float(pct) > 95 else "⚠️ "
        logger.info(f"  {status} {symbol:<12} | {indicators:>8,} / {candles:>8,} candles | {pct}% coverage")
        if float(pct) < 95:
            ok = False
    return ok


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Phase 4 — Indicator Engine Verification")
    logger.info("=" * 55)

    results = {
        "Row counts":  check_indicator_counts(),
        "Values":      check_indicator_values(),
        "Coverage":    check_coverage(),
    }

    logger.info("=" * 55)
    if all(results.values()):
        logger.success("Phase 4 verification PASSED — indicators ready for ML.")
        logger.success("Ready to proceed to Phase 5 (Machine Learning).")
    else:
        failed = [k for k, v in results.items() if not v]
        logger.warning(f"Issues found: {failed}")
