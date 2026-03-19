"""
check_setup.py — Phase 1 health check
Run this after `docker compose up -d` to verify everything is connected.

Usage:
    python check_setup.py
"""

import sys
from loguru import logger


def check_postgres():
    try:
        import psycopg2
        from config import db
        conn = psycopg2.connect(
            host=db.HOST, port=db.PORT,
            user=db.USER, password=db.PASSWORD,
            dbname=db.DB, connect_timeout=5
        )
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public';")
        table_count = cur.fetchone()[0]
        conn.close()
        logger.success(f"PostgreSQL OK — {table_count} table(s) in public schema")
        return True
    except Exception as e:
        logger.error(f"PostgreSQL FAILED — {e}")
        return False


def check_redis():
    try:
        import redis
        from config import redis_cfg
        r = redis.Redis(
            host=redis_cfg.HOST,
            port=redis_cfg.PORT,
            password=redis_cfg.PASSWORD,
            socket_connect_timeout=5,
            decode_responses=True
        )
        r.ping()
        info = r.info("server")
        logger.success(f"Redis OK — version {info['redis_version']}")
        return True
    except Exception as e:
        logger.error(f"Redis FAILED — {e}")
        return False


def check_ollama():
    try:
        import httpx
        from config import ollama
        r = httpx.get(f"{ollama.url}/api/tags", timeout=5)
        models = [m["name"] for m in r.json().get("models", [])]
        if models:
            logger.success(f"Ollama OK — models available: {', '.join(models)}")
        else:
            logger.warning("Ollama reachable but no models pulled yet — run: ollama pull llama3")
        return True
    except Exception as e:
        logger.warning(f"Ollama NOT reachable — {e}")
        logger.warning("This is OK for Phase 1. Ollama is needed in Phase 6.")
        return True  # not blocking for phase 1


def check_tables():
    try:
        import psycopg2
        from config import db
        expected = ["market_data", "indicators", "predictions", "trade_decisions", "trades"]
        conn = psycopg2.connect(
            host=db.HOST, port=db.PORT,
            user=db.USER, password=db.PASSWORD,
            dbname=db.DB
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        found = [row[0] for row in cur.fetchall()]
        conn.close()
        missing = [t for t in expected if t not in found]
        if missing:
            logger.error(f"Missing tables: {missing}")
            return False
        logger.success(f"All tables present: {expected}")
        return True
    except Exception as e:
        logger.error(f"Table check FAILED — {e}")
        return False


if __name__ == "__main__":
    logger.info("=" * 50)
    logger.info("AI Trading Platform — Phase 1 Health Check")
    logger.info("=" * 50)

    results = {
        "PostgreSQL connection": check_postgres(),
        "Database tables":      check_tables(),
        "Redis connection":     check_redis(),
        "Ollama (optional)":    check_ollama(),
    }

    logger.info("-" * 50)
    all_critical = results["PostgreSQL connection"] and results["Database tables"] and results["Redis connection"]

    if all_critical:
        logger.success("Phase 1 setup COMPLETE. Ready to start Phase 2.")
    else:
        logger.error("Some checks failed. Fix the errors above before continuing.")
        sys.exit(1)
