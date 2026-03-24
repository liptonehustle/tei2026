"""
decision_engine/verify.py
Phase 6 verification — confirm decision engine works end-to-end.

Usage: python -m decision_engine.verify
"""

import sys
sys.path.insert(0, ".")

from loguru import logger
from decision_engine.ollama_client import is_available, ask_json
from decision_engine.prompt_builder import SYSTEM_PROMPT
from decision_engine.engine import make_decision
from database.db import DB, test_connection

SYMBOLS = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]


def check_ollama():
    logger.info("── Ollama connection ───────────────────────────")
    ok = is_available()
    if ok:
        logger.info("  ✅ Ollama reachable and model loaded")
    else:
        logger.error("  ❌ Ollama not ready — run: ollama pull llama3")
    return ok


def check_json_output():
    logger.info("── JSON output test ────────────────────────────")
    test_prompt = """Return this exact JSON, nothing else:
{"action": "hold", "entry_price": null, "stop_loss": null, "take_profit": null, "confidence": 0.5, "reasoning": "test"}"""

    result = ask_json(test_prompt, system=SYSTEM_PROMPT)
    if result and result.get("action") == "hold":
        logger.info("  ✅ Ollama returns valid JSON")
        return True
    else:
        logger.error(f"  ❌ JSON output test failed: {result}")
        return False


def check_decisions():
    logger.info("── Decision engine test ────────────────────────")
    ok = True
    for symbol in SYMBOLS:
        d = make_decision(symbol)
        if not d:
            logger.error(f"  ❌ {symbol} — decision failed")
            ok = False
            continue

        emoji = "🟢" if d["action"] == "buy" else \
                "🔴" if d["action"] == "sell" else "🟡"
        logger.info(
            f"  {emoji} {symbol:<12} → {d['action'].upper():<4} "
            f"| confidence={d['confidence']:.0%} "
            f"| {d['reasoning'][:60]}..."
        )
    return ok


def check_db_saved():
    logger.info("── DB saved decisions ──────────────────────────")
    sql = """
        SELECT symbol, action, confidence, created_at
        FROM trade_decisions
        ORDER BY created_at DESC
        LIMIT 5;
    """
    with DB() as (_, cur):
        cur.execute(sql)
        rows = cur.fetchall()

    if not rows:
        logger.warning("  No decisions in DB yet")
        return False

    for symbol, action, conf, ts in rows:
        logger.info(f"  {symbol:<12} {action:<4} conf={float(conf):.0%} @ {ts.strftime('%H:%M:%S')}")
    return True


if __name__ == "__main__":
    logger.info("=" * 55)
    logger.info("Phase 6 — Decision Engine Verification")
    logger.info("=" * 55)

    if not test_connection():
        logger.error("PostgreSQL not reachable.")
        sys.exit(1)

    results = {
        "Ollama":       check_ollama(),
        "JSON output":  check_json_output(),
        "Decisions":    check_decisions(),
        "DB saved":     check_db_saved(),
    }

    logger.info("=" * 55)
    if all(results.values()):
        logger.success("Phase 6 PASSED — Decision engine ready!")
        logger.success("Ready to proceed to Phase 7 (Automated Trading).")
    else:
        failed = [k for k, v in results.items() if not v]
        logger.error(f"Issues: {failed}")
