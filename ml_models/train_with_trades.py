"""
ml_models/train_with_trades.py
Train ML model menggunakan data dari real trades
"""

import sys
sys.path.insert(0, ".")

from loguru import logger
from ml_models.trainer import train_symbol, SYMBOLS
from database.db import DB

def check_trade_availability(symbol: str, min_trades: int = 30) -> bool:
    """Cek apakah ada cukup closed trade untuk training"""
    with DB() as (conn, cur):
        cur.execute("""
            SELECT COUNT(*) FROM trades 
            WHERE symbol = %s AND status = 'closed' AND profit_loss IS NOT NULL
        """, (symbol,))
        count = cur.fetchone()[0]
    logger.info(f"  {symbol}: {count} closed trades available")
    return count >= min_trades

def train_all_with_trades(min_trades: int = 30):
    """Train semua symbol yang punya cukup data trade"""
    results = {}
    for symbol in SYMBOLS:
        if check_trade_availability(symbol, min_trades):
            logger.info(f"✅ Training {symbol} with real trade data...")
            results[symbol] = train_symbol(symbol, "both")
        else:
            logger.warning(f"⚠️ Skipping {symbol} — insufficient trade data")
            results[symbol] = None
    return results

if __name__ == "__main__":
    logger.info("Training ML with real trade labels")
    results = train_all_with_trades()
    
    logger.info("\n" + "="*55)
    logger.info("Training Summary:")
    for symbol, result in results.items():
        if result:
            logger.success(f"✅ {symbol}: {result}")
        else:
            logger.error(f"❌ {symbol}: failed or skipped")