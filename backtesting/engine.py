"""
backtesting/engine.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 5.5 — Backtesting Engine

Simulates the full trading pipeline on historical data:
  1. Load historical candles + indicators
  2. Run ML model predictions on each candle
  3. Apply simple entry/exit rules
  4. Apply risk management rules
  5. Calculate P&L, Sharpe ratio, drawdown

Usage:
  python -m backtesting.engine --symbol BTC/USDT --days 30
  python -m backtesting.engine --symbol all --days 30
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from loguru import logger

from ml_models.features import build_features, FEATURE_COLS
from ml_models.trainer import load_model, get_latest_version
from database.db import test_connection

os.makedirs("logs", exist_ok=True)
os.makedirs("docs/backtest_results", exist_ok=True)
logger.add("logs/backtest.log", rotation="10 MB", retention="7 days")

SYMBOLS   = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAME = "5m"

# ── Strategy parameters ────────────────────────────────
PROB_UP_THRESHOLD = 0.70
PROB_DN_THRESHOLD = 0.70
STOP_LOSS_PCT     = 0.008
TAKE_PROFIT_PCT   = 0.020
MAX_HOLD_CANDLES  = 30

# ── Risk parameters ────────────────────────────────────
INITIAL_CAPITAL    = 10_000.0
RISK_PER_TRADE_PCT = 0.01
MAX_OPEN_TRADES    = 3
DAILY_LOSS_LIMIT   = 0.05
FEE_PCT            = 0.001


# ══════════════════════════════════════════════════════
# ENGINE
# ══════════════════════════════════════════════════════

class BacktestEngine:
    def __init__(self, symbol: str):
        self.symbol          = symbol
        self.capital         = INITIAL_CAPITAL
        self.initial_capital = INITIAL_CAPITAL
        self.open_trades     = []
        self.closed_trades   = []
        self.equity_curve    = []   # list of (timestamp, equity)
        self.daily_pnl       = {}

    def _position_size(self, entry_price: float) -> float:
        risk_amount  = self.capital * RISK_PER_TRADE_PCT
        stop_loss_px = entry_price * STOP_LOSS_PCT
        qty          = risk_amount / stop_loss_px if stop_loss_px > 0 else 0
        return round(qty, 6)

    def _check_risk(self, ts: datetime) -> bool:
        if len(self.open_trades) >= MAX_OPEN_TRADES:
            return False
        day_key = ts.date() if hasattr(ts, "date") else ts
        day_pnl = self.daily_pnl.get(day_key, 0.0)
        if day_pnl <= -(self.initial_capital * DAILY_LOSS_LIMIT):
            return False
        return True

    def _open_trade(self, ts, side: str, price: float):
        qty = self._position_size(price)
        if qty <= 0:
            return
        fee = price * qty * FEE_PCT
        self.capital -= fee

        sl = price * (1 - STOP_LOSS_PCT) if side == "buy" else price * (1 + STOP_LOSS_PCT)
        tp = price * (1 + TAKE_PROFIT_PCT) if side == "buy" else price * (1 - TAKE_PROFIT_PCT)

        self.open_trades.append({
            "side": side, "entry_price": price, "entry_time": ts,
            "stop_loss": sl, "take_profit": tp,
            "quantity": qty, "candles_held": 0,
        })

    def _update_trades(self, ts, close: float):
        still_open = []
        for t in self.open_trades:
            t["candles_held"] += 1
            exit_px     = None
            exit_reason = None

            # Use close price as proxy (no intra-candle OHLC in DB)
            if t["side"] == "buy":
                if close <= t["stop_loss"]:
                    exit_px, exit_reason = t["stop_loss"], "stop_loss"
                elif close >= t["take_profit"]:
                    exit_px, exit_reason = t["take_profit"], "take_profit"
            else:
                if close >= t["stop_loss"]:
                    exit_px, exit_reason = t["stop_loss"], "stop_loss"
                elif close <= t["take_profit"]:
                    exit_px, exit_reason = t["take_profit"], "take_profit"

            if t["candles_held"] >= MAX_HOLD_CANDLES and exit_px is None:
                exit_px, exit_reason = close, "timeout"

            if exit_px:
                fee = exit_px * t["quantity"] * FEE_PCT
                pnl = ((exit_px - t["entry_price"]) * t["quantity"] - fee) \
                      if t["side"] == "buy" else \
                      ((t["entry_price"] - exit_px) * t["quantity"] - fee)

                self.capital += pnl
                day_key = ts.date() if hasattr(ts, "date") else ts
                self.daily_pnl[day_key] = self.daily_pnl.get(day_key, 0.0) + pnl

                self.closed_trades.append({
                    **t, "exit_price": exit_px, "exit_time": ts,
                    "exit_reason": exit_reason, "pnl": pnl,
                })
            else:
                still_open.append(t)

        self.open_trades = still_open
        self.equity_curve.append((ts, self.capital))

    def run(self, df: pd.DataFrame, prob_up_arr: np.ndarray) -> dict:
        logger.info(f"Simulating {self.symbol} | {len(df):,} candles...")

        for i, row in enumerate(df.itertuples(index=False)):
            ts    = row.timestamp
            close = float(row.close)
            prob  = float(prob_up_arr[i])

            self._update_trades(ts, close)

            if self._check_risk(ts):
                if prob >= PROB_UP_THRESHOLD:
                    self._open_trade(ts, "buy", close)
                elif (1 - prob) >= PROB_DN_THRESHOLD:
                    self._open_trade(ts, "sell", close)

        # Close remaining trades at last price
        if len(df) > 0:
            last_close = float(df.iloc[-1]["close"])
            last_ts    = df.iloc[-1]["timestamp"]
            for t in self.open_trades:
                fee = last_close * t["quantity"] * FEE_PCT
                pnl = ((last_close - t["entry_price"]) * t["quantity"] - fee) \
                      if t["side"] == "buy" else \
                      ((t["entry_price"] - last_close) * t["quantity"] - fee)
                self.capital += pnl
                self.closed_trades.append({
                    **t, "exit_price": last_close, "exit_time": last_ts,
                    "exit_reason": "end_of_backtest", "pnl": pnl,
                })
            self.open_trades = []

        return self._metrics()

    def _metrics(self) -> dict:
        trades = self.closed_trades
        if not trades:
            logger.warning("No trades executed")
            return {}

        pnls         = [t["pnl"] for t in trades]
        total_pnl    = sum(pnls)
        total_return = total_pnl / self.initial_capital
        wins         = [p for p in pnls if p > 0]
        losses       = [p for p in pnls if p <= 0]
        win_rate     = len(wins) / len(trades)

        # Sharpe from equity curve
        eq_values = [e for _, e in self.equity_curve]
        if len(eq_values) > 1:
            eq_series = pd.Series(eq_values)
            rets      = eq_series.pct_change().dropna()
            sharpe    = float(rets.mean() / rets.std() * np.sqrt(525_600)) \
                        if rets.std() > 0 else 0.0
        else:
            sharpe = 0.0

        # Max drawdown
        eq_arr  = np.array(eq_values)
        peak    = np.maximum.accumulate(eq_arr)
        dd      = (eq_arr - peak) / np.where(peak > 0, peak, 1)
        max_dd  = float(dd.min())

        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 999.0

        return {
            "symbol":        self.symbol,
            "total_trades":  len(trades),
            "win_rate":      round(win_rate, 4),
            "total_pnl":     round(total_pnl, 4),
            "total_return":  round(total_return, 4),
            "sharpe_ratio":  round(sharpe, 4),
            "max_drawdown":  round(max_dd, 4),
            "profit_factor": round(profit_factor, 4),
            "avg_win":       round(float(np.mean(wins)) if wins else 0, 4),
            "avg_loss":      round(float(np.mean(losses)) if losses else 0, 4),
            "final_capital": round(self.capital, 2),
        }


# ══════════════════════════════════════════════════════
# RUN
# ══════════════════════════════════════════════════════

def run_backtest(symbol: str, days: int = 30, model_type: str = "rf") -> dict:
    logger.info("=" * 55)
    logger.info(f"Backtest: {symbol} | {days} days | model: {model_type}")
    logger.info("=" * 55)

    version = get_latest_version(symbol, model_type)
    if not version:
        logger.error(f"No model found for {symbol} — run trainer first")
        return {}
    logger.info(f"Model loaded: {version}")

    df = build_features(symbol, timeframe=TIMEFRAME, limit=days * 1440)
    if df.empty:
        return {}

    # Use last N days
    cutoff = df["timestamp"].max() - pd.Timedelta(days=days)
    df     = df[df["timestamp"] >= cutoff].reset_index(drop=True)
    logger.info(f"Backtest window: {len(df):,} candles")

    # Generate predictions
    model, scaler, _ = load_model(version)
    X        = df[FEATURE_COLS].values
    X_scaled = scaler.transform(X)
    prob_up  = model.predict_proba(X_scaled)[:, 1]

    # Simulate
    engine  = BacktestEngine(symbol)
    metrics = engine.run(df, prob_up)
    if not metrics:
        return {}

    # Print results
    logger.info(f"  Total trades:  {metrics['total_trades']}")
    logger.info(f"  Win rate:      {metrics['win_rate']:.1%}")
    logger.info(f"  Total P&L:     {metrics['total_pnl']:+.2f} USDT ({metrics['total_return']:+.1%})")
    logger.info(f"  Sharpe ratio:  {metrics['sharpe_ratio']:.3f}")
    logger.info(f"  Max drawdown:  {metrics['max_drawdown']:.1%}")
    logger.info(f"  Profit factor: {metrics['profit_factor']:.2f}")
    logger.info(f"  Final capital: {metrics['final_capital']:.2f} USDT")

    if metrics["sharpe_ratio"] > 0.5 and metrics["total_return"] > 0:
        logger.success("✅ PASS — positive return + acceptable Sharpe")
    elif metrics["total_return"] > 0:
        logger.warning(f"⚠️  MARGINAL — positive return but low Sharpe ({metrics['sharpe_ratio']:.3f})")
    else:
        logger.warning("❌ FAIL — negative return. Do NOT go live.")

    # Save to file
    out = Path(f"docs/backtest_results/{symbol.replace('/','')}__{days}d__{model_type}.json")
    with open(out, "w") as f:
        json.dump({**metrics, "model_version": version, "days": days,
                   "run_at": datetime.now(timezone.utc).isoformat()}, f, indent=2)
    logger.info(f"Saved: {out}")

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtesting Engine — Phase 5.5")
    parser.add_argument("--symbol", default="BTC/USDT", help="Symbol or 'all'")
    parser.add_argument("--days",   default=30, type=int)
    parser.add_argument("--model",  default="rf", choices=["xgb", "rf"])
    args = parser.parse_args()

    if not test_connection():
        logger.error("PostgreSQL not reachable.")
        sys.exit(1)

    if args.symbol == "all":
        results = []
        for s in SYMBOLS:
            m = run_backtest(s, args.days, args.model)
            if m:
                results.append(m)
        if results:
            logger.info("=" * 55)
            logger.info("PORTFOLIO SUMMARY")
            logger.info("=" * 55)
            avg_sharpe = np.mean([m["sharpe_ratio"] for m in results])
            avg_return = np.mean([m["total_return"] for m in results])
            logger.info(f"  Avg Sharpe: {avg_sharpe:.3f}")
            logger.info(f"  Avg Return: {avg_return:+.1%}")
            if avg_sharpe > 0.5 and avg_return > 0:
                logger.success("✅ Portfolio PASS — ready for Phase 6")
            else:
                logger.warning("⚠️  Needs improvement before Phase 7")
    else:
        run_backtest(args.symbol, args.days, args.model)
