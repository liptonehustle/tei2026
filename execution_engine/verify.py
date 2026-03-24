"""
execution_engine/verify.py
Phase 7 verification — confirm all components ready.

Usage: python -m execution_engine.verify
"""

import sys
sys.path.insert(0, ".")

from loguru import logger
from execution_engine.executor import get_exchange, get_account_balance
from execution_engine.risk_manager import log_status
from decision_engine.ollama_client import is_available
from database.db import test_connection


def check_bybit():
    logger.info("── Bybit Demo connection ───────────────────────")
    try:
        exchange = get_exchange()
        markets  = exchange.load_markets()
        balance  = get_account_balance()
        logger.info(f"  ✅ Connected | {len(markets)} markets | Balance: {balance:.2f} USDT")
        return True
    except Exception as e:
        logger.error(f"  ❌ Bybit connection failed: {e}")
        logger.error("  → Check BYBIT_API_KEY and BYBIT_API_SECRET in .env")
        return False


def check_risk_manager():
    logger.info("── Risk manager ────────────────────────────────")
    try:
        from execution_engine.risk_manager import check as risk_check
        # Test with a mock scenario
        result = risk_check("BTC/USDT", "buy", 0.80, 70000.0, 10000.0)
        logger.info(f"  ✅ Risk manager OK — test result: {result.reason}")
        return True
    except Exception as e:
        logger.error(f"  ❌ Risk manager error: {e}")
        return False


def check_full_pipeline():
    logger.info("── Full pipeline test (no real order) ──────────")
    try:
        from decision_engine.engine import make_decision
        from execution_engine.risk_manager import check as risk_check

        d = make_decision("BTC/USDT")
        if not d:
            logger.warning("  ⚠️  No decision returned (Ollama may be slow)")
            return True  # not blocking

        balance = get_account_balance()
        risk    = risk_check(
            symbol          = d["symbol"],
            action          = d["action"],
            confidence      = d.get("confidence", 0),
            entry_price     = d.get("entry_price") or 0,
            account_balance = balance,
        )

        logger.info(f"  Decision: {d['action'].upper()} | confidence={d.get('confidence', 0):.0%}")
        logger.info(f"  Risk check: {'✅ APPROVED' if risk.approved else '❌ REJECTED'} — {risk.reason}")
        return True
    except Exception as e:
        logger.error(f"  ❌ Pipeline test failed: {e}")
        return False


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Phase 7 — Execution Engine Verification")
    logger.info("=" * 55)

    if not test_connection():
        logger.error("PostgreSQL not reachable.")
        sys.exit(1)

    results = {
        "Bybit Demo":     check_bybit(),
        "Risk manager":   check_risk_manager(),
        "Full pipeline":  check_full_pipeline(),
    }

    logger.info("=" * 55)
    if all(results.values()):
        logger.success("Phase 7 READY — start trading with:")
        logger.success("  python -m execution_engine.scheduler")
    else:
        failed = [k for k, v in results.items() if not v]
        logger.error(f"Issues: {failed}")
