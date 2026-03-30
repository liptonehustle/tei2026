"""
utils/warp.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Cloudflare WARP auto-reconnect utility

Checks connection to Bybit every cycle.
Auto-reconnects WARP if connection is lost.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import subprocess
import requests
from loguru import logger

WARP_CLI = r"C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe"
TEST_URL  = "https://api.bybit.com/v5/market/time"


def is_connected() -> bool:
    """Check if Bybit is reachable."""
    try:
        r = requests.get(TEST_URL, timeout=5)
        return r.status_code == 200
    except Exception:
        return False


def warp_status() -> str:
    """Get WARP connection status."""
    try:
        result = subprocess.run(
            [WARP_CLI, "status"],
            capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception as e:
        return f"unknown: {e}"


def warp_connect() -> bool:
    """Connect WARP."""
    try:
        subprocess.run(
            [WARP_CLI, "connect"],
            capture_output=True, text=True, timeout=15
        )
        import time
        time.sleep(3)  # wait for connection
        return is_connected()
    except Exception as e:
        logger.error(f"WARP connect failed: {e}")
        return False


def ensure_connected() -> bool:
    """
    Ensure Bybit is reachable.
    Auto-reconnects WARP if connection is lost.
    Returns True if connected, False if failed.
    """
    if is_connected():
        return True

    logger.warning("Bybit not reachable — attempting WARP reconnect...")
    status = warp_status()
    logger.info(f"WARP status: {status}")

    success = warp_connect()
    if success:
        logger.success("WARP reconnected — Bybit reachable again ✅")
    else:
        logger.error("WARP reconnect failed — Bybit still not reachable ❌")

    return success