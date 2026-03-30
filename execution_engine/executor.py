"""
execution_engine/executor.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 7 — Order Executor
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

import os
from datetime import datetime, timezone

import ccxt
from loguru import logger
from dotenv import load_dotenv

from database.queries import save_trade, close_trade, get_open_trades
from execution_engine.risk_manager import check as risk_check, log_status
from notifications.telegram import alert_order_executed

load_dotenv()

# ── Config ─────────────────────────────────────────────────
BYBIT_API_KEY    = os.getenv("BYBIT_API_KEY", "")
BYBIT_API_SECRET = os.getenv("BYBIT_API_SECRET", "")
BYBIT_DEMO       = os.getenv("BYBIT_DEMO", "true").lower() == "true"
ACCOUNT_BALANCE  = float(os.getenv("ACCOUNT_BALANCE", "10000"))
LEVERAGE         = int(os.getenv("BYBIT_LEVERAGE", "10"))
MARGIN_MODE      = os.getenv("BYBIT_MARGIN_MODE", "isolated")

# Minimum quantity per symbol (Bybit Futures)
MIN_QUANTITY = {
    "BTC/USDT": 0.001,
    "ETH/USDT": 0.01,
    "BNB/USDT": 0.01,
}

_exchange: ccxt.bybit | None = None


# ═══════════════════════════════════════════════════════════
# EXCHANGE & BALANCE
# ═══════════════════════════════════════════════════════════

def get_exchange() -> ccxt.bybit:
    global _exchange
    if _exchange is None:
        if BYBIT_DEMO:
            _exchange = ccxt.bybit({
                "enableRateLimit": True,
                "options": {"defaultType": "linear"},
            })
            logger.info("Bybit exchange initialized [PAPER TRADING]")
        else:
            _exchange = ccxt.bybit({
                "apiKey": BYBIT_API_KEY,
                "secret": BYBIT_API_SECRET,
                "enableRateLimit": True,
                "options": {"defaultType": "linear"},
            })
            logger.info("Bybit exchange initialized [LIVE]")
    return _exchange


def get_account_balance() -> float:
    if BYBIT_DEMO:
        logger.info(f"[PAPER] Account balance: {ACCOUNT_BALANCE:.2f} USDT")
        return ACCOUNT_BALANCE

    try:
        exchange = get_exchange()
        balance = exchange.fetch_balance()
        usdt = float(balance.get("USDT", {}).get("free", 0))
        logger.info(f"Account balance: {usdt:.2f} USDT")
        return usdt if usdt > 0 else ACCOUNT_BALANCE
    except Exception as e:
        logger.warning(f"Could not fetch live balance ({e}) — using config")
        return ACCOUNT_BALANCE


def _get_current_price(symbol: str) -> float:
    try:
        exchange = get_exchange()
        ticker = exchange.fetch_ticker(symbol)
        return float(ticker["last"])
    except Exception as e:
        logger.warning(f"Could not fetch price for {symbol}: {e}")
        return 0.0


def set_leverage(symbol: str):
    if BYBIT_DEMO:
        return
    try:
        exchange = get_exchange()
        exchange.set_leverage(LEVERAGE, symbol)
        logger.info(f"Leverage set: {symbol} {LEVERAGE}x [{MARGIN_MODE}]")
    except Exception as e:
        logger.warning(f"Could not set leverage for {symbol}: {e}")


# ═══════════════════════════════════════════════════════════
# ORDER PLACEMENT
# ═══════════════════════════════════════════════════════════

def place_order(symbol: str, side: str, quantity: float, decision_id: int = None) -> dict | None:
    # Minimum quantity check
    min_qty = MIN_QUANTITY.get(symbol, 0.001)
    if quantity < min_qty:
        logger.warning(f"Quantity {quantity:.6f} below minimum {min_qty} — adjusting")
        quantity = min_qty

    if BYBIT_DEMO:
        return _paper_place_order(symbol, side, quantity, decision_id)

    # Live order
    try:
        exchange = get_exchange()
        set_leverage(symbol)
        order = exchange.create_market_order(symbol, side, quantity)
        entry_price = float(order.get("average") or order.get("price") or 0)
        order_id = order.get("id", "unknown")

        logger.success(
            f"✅ Order placed: {symbol} {side.upper()} "
            f"qty={quantity:.6f} @ {entry_price:.4f} USDT [id={order_id}]"
        )

        trade_id = save_trade({
            "timestamp": datetime.now(timezone.utc),
            "symbol": symbol,
            "side": side,
            "entry_price": entry_price,
            "quantity": quantity,
            "status": "open",
            "decision_id": decision_id,
            "notes": f"bybit_order_id={order_id}",
        })
        alert_order_executed(symbol, side, quantity, entry_price, trade_id)

        return {"trade_id": trade_id, "order_id": order_id,
                "symbol": symbol, "side": side,
                "quantity": quantity, "entry_price": entry_price}

    except Exception as e:
        logger.error(f"Order failed [{symbol} {side}]: {e}")
        return None


def _paper_place_order(symbol: str, side: str, quantity: float, decision_id: int = None) -> dict | None:
    entry_price = _get_current_price(symbol)
    if entry_price <= 0:
        logger.error(f"[PAPER] Could not get price for {symbol}")
        return None

    order_id = f"paper_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"

    logger.success(
        f"📝 [PAPER] Order: {symbol} {side.upper()} "
        f"qty={quantity:.6f} @ {entry_price:.4f} USDT [id={order_id}]"
    )

    trade_id = save_trade({
        "timestamp": datetime.now(timezone.utc),
        "symbol": symbol,
        "side": side,
        "entry_price": entry_price,
        "quantity": quantity,
        "status": "open",
        "decision_id": decision_id,
        "notes": f"paper_order_id={order_id}",
    })
    alert_order_executed(symbol, side, quantity, entry_price, trade_id)

    return {"trade_id": trade_id, "order_id": order_id,
            "symbol": symbol, "side": side,
            "quantity": quantity, "entry_price": entry_price}


# ═══════════════════════════════════════════════════════════
# EXECUTE DECISION
# ═══════════════════════════════════════════════════════════

def execute_decision(decision: dict) -> dict | None:
    symbol = decision["symbol"]
    action = decision["action"]
    confidence = float(decision.get("confidence", 0))
    entry_price = float(decision.get("entry_price") or 0)
    decision_id = decision.get("decision_id")

    logger.info(f"─── Executing: {symbol} {action.upper()} ───────────────")

    balance = get_account_balance()
    log_status(balance)

    # Fetch ATR
    from database.queries import get_indicators
    _ind = get_indicators(symbol, limit=1)
    _atr = float(_ind.iloc[-1]["atr"]) if not _ind.empty else 0

    logger.info(f"  Entry price: {entry_price:.4f} | ATR: {_atr:.4f}")

    risk = risk_check(
        symbol=symbol, action=action,
        confidence=confidence, entry_price=entry_price,
        account_balance=balance, atr=_atr,
    )

    if not risk.approved:
        logger.warning(f"❌ Risk REJECTED: {symbol} — {risk.reason}")
        return None

    logger.info(f"  ✅ Risk approved: qty={risk.quantity:.6f} | margin={risk.margin_required:.2f} USDT")

    return place_order(symbol, action, risk.quantity, decision_id)


# ═══════════════════════════════════════════════════════════
# CLOSE POSITION
# ═══════════════════════════════════════════════════════════

def close_position(trade_id: int, symbol: str, side: str, quantity: float) -> bool:
    if BYBIT_DEMO:
        return _paper_close_position(trade_id, symbol, side, quantity)

    # Live close
    close_side = "sell" if side == "buy" else "buy"
    try:
        exchange = get_exchange()
        order = exchange.create_market_order(symbol, close_side, quantity)
        exit_price = float(order.get("average") or order.get("price") or 0)

        open_trades = get_open_trades()
        trade = next((t for t in open_trades if t["id"] == trade_id), None)
        if trade:
            entry_price = float(trade["entry_price"])
            qty = float(trade["quantity"])
            pnl = (exit_price - entry_price) * qty if side == "buy" else (entry_price - exit_price) * qty
            pnl_pct = pnl / (entry_price * qty) * 100
        else:
            pnl = pnl_pct = 0.0

        close_trade(trade_id, exit_price, pnl, pnl_pct)
        logger.info(f"Position closed: {symbol} exit={exit_price:.4f} P&L={pnl:+.4f}")
        return True

    except Exception as e:
        logger.error(f"Failed to close position [{trade_id}]: {e}")
        return False


def _paper_close_position(trade_id: int, symbol: str, side: str, quantity: float) -> bool:
    exit_price = _get_current_price(symbol)
    if exit_price <= 0:
        logger.error(f"[PAPER] Could not get exit price for {symbol}")
        return False

    open_trades = get_open_trades()
    trade = next((t for t in open_trades if t["id"] == trade_id), None)
    if trade:
        entry_price = float(trade["entry_price"])
        qty = float(trade["quantity"])
        pnl = (exit_price - entry_price) * qty if side == "buy" else (entry_price - exit_price) * qty
        pnl_pct = pnl / (entry_price * qty) * 100
    else:
        pnl = pnl_pct = 0.0

    close_trade(trade_id, exit_price, pnl, pnl_pct)
    logger.info(
        f"📝 [PAPER] Position closed: {symbol} exit={exit_price:.4f} "
        f"P&L={pnl:+.4f} USDT ({pnl_pct:+.2f}%)"
    )
    return True