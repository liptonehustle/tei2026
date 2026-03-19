"""
database/db.py
PostgreSQL connection pool — shared across all services.
Import: from database.db import DB, test_connection
"""

import sys
sys.path.insert(0, ".")

import psycopg2
from psycopg2 import pool
from loguru import logger
from config import db as db_cfg


_pool: pool.SimpleConnectionPool | None = None


def get_pool() -> pool.SimpleConnectionPool:
    global _pool
    if _pool is None:
        _pool = pool.SimpleConnectionPool(
            1, 10,
            host=db_cfg.HOST,
            port=db_cfg.PORT,
            user=db_cfg.USER,
            password=db_cfg.PASSWORD,
            dbname=db_cfg.DB,
        )
        logger.info("PostgreSQL connection pool created (min=1, max=10)")
    return _pool


class DB:
    """
    Context manager for safe DB usage.

    Usage:
        with DB() as (conn, cur):
            cur.execute("SELECT ...")
            # commit is automatic on clean exit
    """

    def __enter__(self):
        self.conn = get_pool().getconn()
        self.cur  = self.conn.cursor()
        return self.conn, self.cur

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.conn.rollback()
            logger.error(f"DB error, rolling back: {exc_val}")
        else:
            self.conn.commit()
        self.cur.close()
        get_pool().putconn(self.conn)
        return False


def test_connection() -> bool:
    """Quick health check — returns True if DB is reachable."""
    try:
        with DB() as (_, cur):
            cur.execute("SELECT 1")
        logger.info("PostgreSQL OK")
        return True
    except Exception as e:
        logger.error(f"PostgreSQL FAILED: {e}")
        return False