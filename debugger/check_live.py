"""
check_live.py — Live trading performance check
Usage: python check_live.py
"""

import sys
sys.path.insert(0, ".")

from database.db import DB
from loguru import logger


def run():
    with DB() as (_, cur):

        # Total closed trades
        cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'closed'")
        total = cur.fetchone()[0]

        # Win rate
        cur.execute("""
            SELECT COALESCE(
                SUM(CASE WHEN profit_loss > 0 THEN 1 ELSE 0 END)::float
                / NULLIF(COUNT(*), 0), 0)
            FROM trades WHERE status = 'closed'
        """)
        win_rate = float(cur.fetchone()[0])

        # Total P&L
        cur.execute("SELECT COALESCE(SUM(profit_loss), 0) FROM trades WHERE status = 'closed'")
        total_pnl = float(cur.fetchone()[0])

        # Date range
        cur.execute("SELECT MIN(closed_at), MAX(closed_at) FROM trades WHERE status = 'closed'")
        date_range = cur.fetchone()

        # Open trades
        cur.execute("SELECT COUNT(*) FROM trades WHERE status = 'open'")
        open_trades = cur.fetchone()[0]

        # Total decisions made
        cur.execute("SELECT COUNT(*), action FROM trade_decisions GROUP BY action ORDER BY action")
        decisions = cur.fetchall()

    logger.info("=" * 55)
    logger.info("Live Trading Performance Check")
    logger.info("=" * 55)
    logger.info(f"  Closed trades:  {total}")
    logger.info(f"  Open trades:    {open_trades}")
    logger.info(f"  Win rate:       {win_rate:.1%}")
    logger.info(f"  Total P&L:      {total_pnl:+.4f} USDT")
    if date_range[0]:
        logger.info(f"  Date range:     {date_range[0]} → {date_range[1]}")
    logger.info("── Decisions breakdown ─────────────────────────")
    for count, action in decisions:
        logger.info(f"  {action:<8} {count:>6} decisions")
    logger.info("=" * 55)


if __name__ == "__main__":
    run()