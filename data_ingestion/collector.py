"""
data_ingestion/collector.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 2 — Data Collector (Bybit)

What it does:
  1. Connects to Bybit via ccxt (no API key needed for OHLCV)
  2. Fetches the latest closed OHLCV candle for each symbol
  3. Saves to PostgreSQL (market_data table)
  4. Pushes to Redis queue for indicator engine
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import os
import sys
from datetime import datetime, timezone

import ccxt
import redis as redis_lib
from loguru import logger

sys.path.insert(0, ".")
from config import redis_cfg
from database.db import DB, test_connection

os.makedirs("logs", exist_ok=True)
logger.add("logs/collector.log", rotation="10 MB", retention="7 days", level="INFO")

_redis: redis_lib.Redis | None = None

def get_redis() -> redis_lib.Redis:
    global _redis
    if _redis is None:
        _redis = redis_lib.Redis(
            host=redis_cfg.HOST,
            port=redis_cfg.PORT,
            password=redis_cfg.PASSWORD,
            decode_responses=True
        )
    return _redis

# ── Constants ──────────────────────────────────────────────
SYMBOLS   = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAME = "1m"
SOURCE    = "bybit"

# ── Exchange ───────────────────────────────────────────────

def get_exchange() -> ccxt.Exchange:
    exchange = ccxt.bybit({
        "enableRateLimit": True,
        "options": {"defaultType": "spot"},
    })
    logger.info(f"Exchange ready: {SOURCE} | symbols: {SYMBOLS} | timeframe: {TIMEFRAME}")
    return exchange

# ── Fetch ──────────────────────────────────────────────────

def fetch_candle(exchange: ccxt.Exchange, symbol: str) -> dict | None:
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=TIMEFRAME, limit=2)
        if not ohlcv or len(ohlcv) < 2:
            logger.warning(f"Not enough data returned for {symbol}")
            return None

        ts_ms, o, h, l, c, v = ohlcv[-2]
        return {
            "timestamp": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc),
            "symbol":    symbol,
            "timeframe": TIMEFRAME,
            "open":      float(o),
            "high":      float(h),
            "low":       float(l),
            "close":     float(c),
            "volume":    float(v),
            "source":    SOURCE,
        }
    except ccxt.NetworkError as e:
        logger.error(f"[{symbol}] Network error: {e}")
    except ccxt.ExchangeError as e:
        logger.error(f"[{symbol}] Exchange error: {e}")
    except Exception as e:
        logger.error(f"[{symbol}] Unexpected error: {e}")
    return None

# ── Save ───────────────────────────────────────────────────

def save_to_db(candle: dict) -> bool:
    sql = """
        INSERT INTO market_data
            (timestamp, symbol, timeframe, open, high, low, close, volume, source)
        VALUES
            (%(timestamp)s, %(symbol)s, %(timeframe)s,
             %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(source)s)
        ON CONFLICT (timestamp, symbol, timeframe, source) DO NOTHING;
    """
    try:
        with DB() as (conn, cur):
            cur.execute(sql, candle)
        return True
    except Exception as e:
        logger.error(f"[{candle['symbol']}] DB insert failed: {e}")
        return False


def push_to_queue(candle: dict) -> bool:
    try:
        payload = {**candle, "timestamp": candle["timestamp"].isoformat()}
        get_redis().lpush("raw:market_data", json.dumps(payload))
        return True
    except Exception as e:
        logger.error(f"[{candle['symbol']}] Redis push failed: {e}")
        return False

# ── Main collection round ──────────────────────────────────

def run_once() -> int:
    exchange = get_exchange()
    ok = 0

    for symbol in SYMBOLS:
        candle = fetch_candle(exchange, symbol)
        if candle is None:
            continue

        db_ok    = save_to_db(candle)
        queue_ok = push_to_queue(candle)

        if db_ok and queue_ok:
            logger.info(
                f"✅ {symbol} | {candle['timestamp'].strftime('%H:%M')} "
                f"| close={candle['close']:,.4f} | vol={candle['volume']:,.2f}"
            )
            ok += 1
        else:
            logger.warning(f"⚠️  {symbol} | partial save — db={db_ok} queue={queue_ok}")

    logger.info(f"Round done: {ok}/{len(SYMBOLS)} symbols OK")
    return ok

# ── Entry point ────────────────────────────────────────────

if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Data Collector (Bybit) — Phase 2")
    logger.info("=" * 55)

    if not test_connection():
        logger.error("PostgreSQL not reachable. Is Docker running?")
        sys.exit(1)

    try:
        get_redis().ping()
        logger.info("✅ Redis OK")
    except Exception as e:
        logger.error(f"❌ Redis not reachable: {e}")
        sys.exit(1)

    run_once()