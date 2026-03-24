"""
execution_engine/risk_manager.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 7 — Risk Manager

HARD GATE: No order passes without clearing all rules.

Rules enforced:
  1. Max risk per trade: 1% of account
  2. Max open trades: 3 simultaneously
  3. Max daily loss: 5% of account
  4. Min confidence threshold: 60%
  5. No duplicate symbol (one trade per symbol at a time)
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
RISK_PER_TRADE_PCT   = 0.01    # 1% of account
MIN_CONFIDENCE       = 0.60    # minimum Ollama confidence
STOP_LOSS_PCT        = 0.008   # 0.8% stop loss
LEVERAGE             = int(os.getenv("BYBIT_LEVERAGE", "10"))



@dataclass
class RiskDecision:
    approved:  bool
    reason:    str
    quantity:  float = 0.0
    risk_amount: float = 0.0
    margin_required: float = 0.0
    liquidation_price: float = 0.0


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

    Returns RiskDecision with approved=True/False and reason.
    If approved, also returns calculated quantity and risk amount.
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

    # Rule 3: No duplicate symbol (live only — paper allows multiple per symbol)
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
    daily_pnl = get_daily_pnl()
    daily_loss_limit = -(account_balance * DAILY_LOSS_LIMIT_PCT)
    if daily_pnl <= daily_loss_limit:
        return RiskDecision(False,
            f"Daily loss limit hit: {daily_pnl:.2f} USDT "
            f"(limit: {daily_loss_limit:.2f} USDT)")

    # Rule 5: Account balance check
    if account_balance <= 0:
        return RiskDecision(False, "Account balance is zero or negative")

    # Calculate position size — futures with leverage
    risk_amount     = account_balance * RISK_PER_TRADE_PCT
    stop_loss_px    = atr * 1.5 if atr > 0 else entry_price * 0.005
    quantity        = risk_amount / stop_loss_px if stop_loss_px > 0 else 0

    if quantity <= 0:
        return RiskDecision(False, "Calculated quantity is zero")

    # Margin required = position value / leverage
    position_value  = entry_price * quantity
    margin_required = position_value / LEVERAGE

    # Liquidation price estimate (simplified)
    # Long:  liquidation ≈ entry * (1 - 1/leverage + maintenance_margin)
    # Short: liquidation ≈ entry * (1 + 1/leverage - maintenance_margin)
    maintenance_margin = 0.005  # 0.5% — Bybit standard
    if action == "buy":
        liquidation_price = round(entry_price * (1 - 1/LEVERAGE + maintenance_margin), 4)
    else:
        liquidation_price = round(entry_price * (1 + 1/LEVERAGE - maintenance_margin), 4)

    # Check margin is sufficient
    if margin_required > account_balance * 0.5:
        return RiskDecision(False,
            f"Margin required {margin_required:.2f} USDT exceeds 50% of balance")

    logger.info(
        f"✅ Risk approved: {symbol} {action.upper()} | "
        f"qty={quantity:.6f} | risk={risk_amount:.2f} USDT | "
        f"margin={margin_required:.2f} USDT | liq={liquidation_price:.4f} | "
        f"leverage={LEVERAGE}x | confidence={confidence:.0%}"
    )

    return RiskDecision(
        approved          = True,
        reason            = "All risk rules passed",
        quantity          = round(quantity, 6),
        risk_amount       = round(risk_amount, 2),
        margin_required   = round(margin_required, 2),
        liquidation_price = liquidation_price,
    )

def log_status(account_balance: float):
    """Log current risk status — call anytime for diagnostics."""
    open_trades = get_open_trades()
    daily_pnl   = get_daily_pnl()
    daily_limit = -(account_balance * DAILY_LOSS_LIMIT_PCT)

    logger.info("── Risk Status ─────────────────────────────────")
    logger.info(f"  Open trades:  {len(open_trades)}/{MAX_OPEN_TRADES}")
    logger.info(f"  Daily P&L:    {daily_pnl:+.2f} USDT (limit: {daily_limit:.2f})")
    logger.info(f"  Account bal:  {account_balance:.2f} USDT")
    for t in open_trades:
        logger.info(f"  → {t['symbol']} {t['side']} @ {float(t['entry_price']):.4f}")
