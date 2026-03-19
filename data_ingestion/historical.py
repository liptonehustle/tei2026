"""
data_ingestion/historical.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Backfill historical OHLCV data from Bybit.

Usage:
  python -m data_ingestion.historical --symbol BTC/USDT --days 30
  python -m data_ingestion.historical --symbol ETH/USDT --days 30 --timeframe 5m
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import argparse
import sys
import time
from datetime import datetime, timezone, timedelta

import ccxt
from loguru import logger
from tqdm import tqdm

sys.path.insert(0, ".")
from data_ingestion.collector import get_exchange, save_to_db, SOURCE, TIMEFRAME
from database.db import test_connection

BATCH_SIZE = 200  # Bybit max per request


def fetch_historical(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
) -> int:
    tf_map   = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
    tf_sec   = tf_map.get(timeframe, 60)
    total    = int((until_ms - since_ms) / 1000 / tf_sec)
    saved    = 0
    current  = since_ms

    logger.info(f"Backfilling {symbol} | {timeframe} | ~{total:,} candles expected")

    with tqdm(total=total, unit="candles", desc=f"{symbol}") as pbar:
        while current < until_ms:
            try:
                ohlcv = exchange.fetch_ohlcv(
                    symbol,
                    timeframe=timeframe,
                    since=current,
                    limit=BATCH_SIZE,
                )
            except ccxt.RateLimitExceeded:
                logger.warning("Rate limit hit — sleeping 10s")
                time.sleep(10)
                continue
            except ccxt.NetworkError as e:
                logger.error(f"Network error: {e} — retrying in 5s")
                time.sleep(5)
                continue
            except Exception as e:
                logger.error(f"Fetch error: {e}")
                break

            if not ohlcv:
                break

            for ts_ms, o, h, l, c, v in ohlcv:
                if ts_ms >= until_ms:
                    break
                candle = {
                    "timestamp": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
                    "symbol":    symbol,
                    "timeframe": timeframe,
                    "open":      float(o),
                    "high":      float(h),
                    "low":       float(l),
                    "close":     float(c),
                    "volume":    float(v),
                    "source":    SOURCE,
                }
                if save_to_db(candle):
                    saved += 1

            pbar.update(len(ohlcv))
            current = ohlcv[-1][0] + 1
            time.sleep(0.2)  # Bybit rate limit: polite delay

    return saved


def backfill(symbol: str, days: int, timeframe: str = "1m"):
    now_ms   = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = int((datetime.now(timezone.utc) - timedelta(days=days)).timestamp() * 1000)

    logger.info(f"{'='*55}")
    logger.info(f"Backfill: {symbol} | last {days} days | timeframe: {timeframe}")
    logger.info(f"From : {datetime.fromtimestamp(since_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    logger.info(f"To   : {datetime.fromtimestamp(now_ms/1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC")
    logger.info(f"{'='*55}")

    exchange = get_exchange()
    saved    = fetch_historical(exchange, symbol, timeframe, since_ms, now_ms)
    logger.success(f"✅ Backfill complete: {saved:,} candles saved for {symbol}")
    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical OHLCV data from Bybit")
    parser.add_argument("--symbol",    default="BTC/USDT", help="e.g. BTC/USDT")
    parser.add_argument("--days",      default=30, type=int, help="How many days back")
    parser.add_argument("--timeframe", default="1m",        help="1m, 5m, 15m, 1h, 4h, 1d")
    args = parser.parse_args()

    if not test_connection():
        logger.error("PostgreSQL not reachable. Is Docker running?")
        sys.exit(1)

    backfill(args.symbol, args.days, args.timeframe)