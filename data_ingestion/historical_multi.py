"""
data_ingestion/historical_multi.py
Backfill multiple timeframes sekaligus.

Usage:
  python -m data_ingestion.historical_multi
"""

import sys
sys.path.insert(0, ".")

from loguru import logger
from data_ingestion.historical import backfill

SYMBOLS     = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAMES  = ["5m", "15m"]
DAYS        = 30

if __name__ == "__main__":
    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            logger.info(f"Backfilling {symbol} {tf}...")
            backfill(symbol, DAYS, tf)
    logger.success("All done! Ready to retrain on 5m/15m.")