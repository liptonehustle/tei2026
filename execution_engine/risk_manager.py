"""
execution_engine/risk_manager.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 7 — Risk Manager (FIXED for $10 balance)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

from dataclasses import dataclass
from loguru import logger
from database.queries import get_open_trades, get_daily_pnl
import os
from dotenv import load_dotenv
load_dotenv()

# ── Risk parameters ────────────────────────────────────
BYBIT_DEMO = os.getenv("BYBIT_DEMO", "true").lower() == "true"
MAX_OPEN_TRADES = 3 if not BYBIT_DEMO else 999
DAILY_LOSS_LIMIT_PCT = 0.05    # 5% of account
RISK_PER_TRADE_PCT   = 0.05    # 5% of account (agresif)
MIN_CONFIDENCE       = 0.50    # turunkan sedikit untuk paper
STOP_LOSS_PCT        = 0.01    # 1% default stop loss
MIN_STOP_LOSS_PCT    = 0.01    # 1% minimum (FIXED)
MAX_STOP_LOSS_PCT    = 0.02    # 2% maximum
LEVERAGE             = int(os.getenv("BYBIT_LEVERAGE", "10"))

# Minimum quantity per symbol (Bybit Futures)
MIN_QUANTITY = {
    "BTC/USDT": 0.001,
    "ETH/USDT": 0.01,
    "BNB/USDT": 0.01,
}


@dataclass
class RiskDecision:
    approved:  bool
    reason:    str
    quantity:  float = 0.0
    risk_amount: float = 0.0
    margin_required: float = 0.0
    liquidation_price: float = 0.0
    position_size_usdt: float = 0.0
    stop_loss_pct: float = 0.0


def check(
    symbol: str,
    action: str,
    confidence: float,
    entry_price: float,
    account_balance: float,
    atr: float = 0,
) -> RiskDecision:
    """
    Main risk gate — call this before every order.
    """
    # Rule 0: Only process buy/sell
    if action not in ("buy", "sell"):
        return RiskDecision(False, f"Action '{action}' is not tradeable")

    # Rule 1: Minimum confidence
    if confidence < MIN_CONFIDENCE:
        return RiskDecision(False,
            f"Confidence {confidence:.0%} below minimum {MIN_CONFIDENCE:.0%}")

    # Rule 2: Max open trades
    open_trades = get_open_trades()
    if len(open_trades) >= MAX_OPEN_TRADES:
        return RiskDecision(False,
            f"Max open trades reached ({len(open_trades)}/{MAX_OPEN_TRADES})")

    # Rule 3: No duplicate symbol (live only)
    if not BYBIT_DEMO:
        open_symbols = [t["symbol"] for t in open_trades]
        if symbol in open_symbols:
            return RiskDecision(False,
                f"Already have open trade for {symbol}")
    
    # Rule 3b: No duplicate entry price (paper trading only)
    if BYBIT_DEMO:
        open_entries = [float(t["entry_price"]) for t in open_trades if t["symbol"] == symbol]
        if any(abs(ep - entry_price) / entry_price < 0.001 for ep in open_entries):
            return RiskDecision(False,
                f"Duplicate entry price for {symbol} — too close to existing open trade")

    # Rule 4: Daily loss limit
    if not BYBIT_DEMO:
        daily_pnl = get_daily_pnl()
        daily_loss_limit = -(account_balance * DAILY_LOSS_LIMIT_PCT)
        if daily_pnl <= daily_loss_limit:
            return RiskDecision(False,
                f"Daily loss limit hit: {daily_pnl:.2f} USDT "
                f"(limit: {daily_loss_limit:.2f} USDT)")

    # Rule 5: Account balance check
    if account_balance <= 0:
        return RiskDecision(False, "Account balance is zero or negative")

    # ── POSITION SIZING (WITH MINIMUM QUANTITY) ─────────────────────────
    # Risk amount in USDT
    risk_amount = account_balance * RISK_PER_TRADE_PCT
    
    # Stop loss percentage (minimum 1% untuk $10 balance)
    if atr > 0:
        atr_stop_pct = (atr * 1.5) / entry_price
        stop_loss_pct = max(atr_stop_pct, MIN_STOP_LOSS_PCT)
        stop_loss_pct = min(stop_loss_pct, MAX_STOP_LOSS_PCT)
    else:
        stop_loss_pct = STOP_LOSS_PCT
    
    # Calculate ideal position size based on risk
    ideal_position_usdt = risk_amount / stop_loss_pct
    ideal_quantity = ideal_position_usdt / entry_price
    
    # Get minimum quantity for this symbol
    min_qty = MIN_QUANTITY.get(symbol, 0.001)
    
    # Adjust quantity to meet minimum exchange requirements
    if ideal_quantity < min_qty:
        quantity = min_qty
        position_size_usdt = quantity * entry_price
        # Recalculate actual stop loss based on adjusted position
        actual_stop_pct = risk_amount / position_size_usdt
        logger.info(f"  ⚠️ Ideal qty {ideal_quantity:.6f} < min {min_qty} — using min qty, stop={actual_stop_pct:.2%}")
    else:
        quantity = ideal_quantity
        position_size_usdt = ideal_position_usdt
        actual_stop_pct = stop_loss_pct
    
    # Margin required with leverage
    margin_required = position_size_usdt / LEVERAGE
    
    # Check margin is sufficient (95% max untuk paper)
    if BYBIT_DEMO:
        max_margin_pct = 0.95  # 95% untuk paper
    else:
        max_margin_pct = 0.50  # 50% untuk live
    
    if margin_required > account_balance * max_margin_pct:
        logger.info(
            f"  Calculation: risk={risk_amount:.2f}, stop={actual_stop_pct:.2%}, "
            f"pos_size={position_size_usdt:.2f}, margin={margin_required:.2f}"
        )
        return RiskDecision(False,
            f"Margin required {margin_required:.2f} USDT exceeds {max_margin_pct:.0%} of balance")
    
    # Liquidation price estimate
    maintenance_margin = 0.005  # 0.5% — Bybit standard
    if action == "buy":
        liquidation_price = round(entry_price * (1 - 1/LEVERAGE + maintenance_margin), 4)
    else:
        liquidation_price = round(entry_price * (1 + 1/LEVERAGE - maintenance_margin), 4)
    
    # Log detailed calculation
    actual_risk = position_size_usdt * actual_stop_pct
    actual_risk_pct = (actual_risk / account_balance) * 100
    
    logger.info(
        f"✅ Risk approved: {symbol} {action.upper()} | "
        f"qty={quantity:.6f} | "
        f"pos={position_size_usdt:.2f} USDT | "
        f"margin={margin_required:.2f} USDT ({margin_required/account_balance:.0%}) | "
        f"risk={actual_risk:.2f} USDT ({actual_risk_pct:.1f}%) | "
        f"stop={actual_stop_pct:.2%} | "
        f"liq={liquidation_price:.4f} | "
        f"confidence={confidence:.0%}"
    )
    
    return RiskDecision(
        approved            = True,
        reason              = "All risk rules passed",
        quantity            = round(quantity, 6),
        risk_amount         = round(actual_risk, 2),
        margin_required     = round(margin_required, 2),
        liquidation_price   = liquidation_price,
        position_size_usdt  = round(position_size_usdt, 2),
        stop_loss_pct       = round(actual_stop_pct, 4),
    )


def log_status(account_balance: float):
    """Log current risk status."""
    open_trades = get_open_trades()
    daily_pnl   = get_daily_pnl()
    daily_limit = -(account_balance * DAILY_LOSS_LIMIT_PCT)

    logger.info("── Risk Status ─────────────────────────────────")
    logger.info(f"  Open trades:  {len(open_trades)}/{MAX_OPEN_TRADES}")
    logger.info(f"  Daily P&L:    {daily_pnl:+.2f} USDT (limit: {daily_limit:.2f})")
    logger.info(f"  Account bal:  {account_balance:.2f} USDT")
    for t in open_trades:
        logger.info(f"  → {t['symbol']} {t['side']} @ {float(t['entry_price']):.4f}")