"""
backtesting/optimizer.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy parameter optimizer.
Tries different threshold/SL/TP combinations and
finds the best Sharpe ratio.

Usage:
  python -m backtesting.optimizer --symbol BTC/USDT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
import json
from pathlib import Path
from itertools import product

sys.path.insert(0, ".")

import numpy as np
import pandas as pd
from loguru import logger

from ml_models.features import build_features, FEATURE_COLS
from ml_models.trainer import load_model, get_latest_version
from database.db import test_connection

SYMBOLS   = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]
TIMEFRAME = "5m"
DAYS      = 20   # use last 20 days for optimization

# ── Parameter grid ─────────────────────────────────────
PROB_THRESHOLDS  = [0.70, 0.75, 0.80, 0.85]   # higher = fewer but higher quality signals
STOP_LOSS_PCTS   = [0.005, 0.008, 0.010]       # 0.5%, 0.8%, 1.0%
TAKE_PROFIT_PCTS = [0.010, 0.015, 0.020]       # 1.0%, 1.5%, 2.0%
MAX_HOLD_LIST    = [15, 30, 60]                 # candles before timeout exit

INITIAL_CAPITAL    = 10_000.0
RISK_PER_TRADE_PCT = 0.01
MAX_OPEN_TRADES    = 3
DAILY_LOSS_LIMIT   = 0.05
FEE_PCT            = 0.001


def simulate(df, prob_up_arr, prob_thresh, sl_pct, tp_pct, max_hold):
    """Lightweight simulation for parameter search."""
    capital    = INITIAL_CAPITAL
    open_t     = []
    closed_t   = []
    equity     = []
    daily_pnl  = {}

    for i, row in enumerate(df.itertuples(index=False)):
        ts    = row.timestamp
        close = float(row.close)
        prob  = float(prob_up_arr[i])

        # Update open trades
        still_open = []
        for t in open_t:
            t["held"] += 1
            exit_px = None
            if t["side"] == "buy":
                if close <= t["sl"]:  exit_px = t["sl"]
                elif close >= t["tp"]: exit_px = t["tp"]
            else:
                if close >= t["sl"]:  exit_px = t["sl"]
                elif close <= t["tp"]: exit_px = t["tp"]
            if t["held"] >= max_hold and exit_px is None:
                exit_px = close
            if exit_px:
                fee = exit_px * t["qty"] * FEE_PCT
                pnl = ((exit_px - t["ep"]) * t["qty"] - fee) if t["side"] == "buy" \
                      else ((t["ep"] - exit_px) * t["qty"] - fee)
                capital += pnl
                day = ts.date() if hasattr(ts, "date") else ts
                daily_pnl[day] = daily_pnl.get(day, 0.0) + pnl
                closed_t.append(pnl)
            else:
                still_open.append(t)
        open_t = still_open
        equity.append(capital)

        # Risk check
        if len(open_t) >= MAX_OPEN_TRADES:
            continue
        day = ts.date() if hasattr(ts, "date") else ts
        if daily_pnl.get(day, 0.0) <= -(INITIAL_CAPITAL * DAILY_LOSS_LIMIT):
            continue

        # Entry
        side = None
        if prob >= prob_thresh:
            side = "buy"
        elif (1 - prob) >= prob_thresh:
            side = "sell"

        if side:
            risk_amt = capital * RISK_PER_TRADE_PCT
            sl_px    = close * sl_pct
            qty      = risk_amt / sl_px if sl_px > 0 else 0
            fee      = close * qty * FEE_PCT
            capital -= fee
            sl  = close * (1 - sl_pct) if side == "buy" else close * (1 + sl_pct)
            tp  = close * (1 + tp_pct) if side == "buy" else close * (1 - tp_pct)
            open_t.append({"side": side, "ep": close, "sl": sl, "tp": tp,
                           "qty": qty, "held": 0})

    if not closed_t or not equity:
        return None

    total_return = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL
    eq = np.array(equity)
    rets = np.diff(eq) / eq[:-1]
    sharpe = float(rets.mean() / rets.std() * np.sqrt(525_600)) \
             if len(rets) > 1 and rets.std() > 0 else -999

    wins   = [p for p in closed_t if p > 0]
    losses = [p for p in closed_t if p <= 0]
    win_rate = len(wins) / len(closed_t)
    pf = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else 999

    return {
        "prob_thresh": prob_thresh,
        "sl_pct":      sl_pct,
        "tp_pct":      tp_pct,
        "max_hold":    max_hold,
        "trades":      len(closed_t),
        "win_rate":    round(win_rate, 4),
        "total_return":round(total_return, 4),
        "sharpe":      round(sharpe, 4),
        "profit_factor": round(pf, 4),
        "final_capital": round(capital, 2),
    }


def optimize(symbol: str, model_type: str = "rf"):
    logger.info("=" * 55)
    logger.info(f"Optimizer: {symbol} | {DAYS} days")
    logger.info("=" * 55)

    version = get_latest_version(symbol, model_type)
    if not version:
        logger.error(f"No model for {symbol}")
        return None

    model, scaler, _ = load_model(version)
    df = build_features(symbol, timeframe=TIMEFRAME, limit=DAYS * 1440)
    if df.empty:
        return None

    cutoff = df["timestamp"].max() - pd.Timedelta(days=DAYS)
    df     = df[df["timestamp"] >= cutoff].reset_index(drop=True)

    X_scaled = scaler.transform(df[FEATURE_COLS].values)
    prob_up  = model.predict_proba(X_scaled)[:, 1]

    # Grid search
    results = []
    combos  = list(product(PROB_THRESHOLDS, STOP_LOSS_PCTS,
                           TAKE_PROFIT_PCTS, MAX_HOLD_LIST))
    logger.info(f"Testing {len(combos)} parameter combinations...")

    for prob_t, sl, tp, hold in combos:
        r = simulate(df, prob_up, prob_t, sl, tp, hold)
        if r:
            results.append(r)

    if not results:
        logger.error("No valid results")
        return None

    # Rank by Sharpe ratio
    results.sort(key=lambda x: x["sharpe"], reverse=True)
    top = results[:5]

    logger.info(f"\n── Top 5 parameter sets for {symbol} ──────────────")
    logger.info(f"{'Thresh':>6} {'SL%':>5} {'TP%':>5} {'Hold':>5} "
                f"{'Trades':>7} {'WR':>6} {'Return':>8} {'Sharpe':>8} {'PF':>6}")
    logger.info("-" * 65)
    for r in top:
        logger.info(
            f"  {r['prob_thresh']:>5.2f} {r['sl_pct']*100:>4.1f}% "
            f"{r['tp_pct']*100:>4.1f}% {r['max_hold']:>5} "
            f"{r['trades']:>7} {r['win_rate']:>5.1%} "
            f"{r['total_return']:>+7.1%} {r['sharpe']:>8.3f} "
            f"{r['profit_factor']:>5.2f}"
        )

    best = top[0]
    logger.success(f"\n✅ Best params for {symbol}:")
    logger.success(f"   PROB_THRESHOLD = {best['prob_thresh']}")
    logger.success(f"   STOP_LOSS_PCT  = {best['sl_pct']}")
    logger.success(f"   TAKE_PROFIT_PCT= {best['tp_pct']}")
    logger.success(f"   MAX_HOLD       = {best['max_hold']}")
    logger.success(f"   → Sharpe={best['sharpe']:.3f} Return={best['total_return']:+.1%} Trades={best['trades']}")

    # Save best params
    out = Path(f"docs/backtest_results/{symbol.replace('/','')}_best_params.json")
    with open(out, "w") as f:
        json.dump({"symbol": symbol, "best": best, "top5": top}, f, indent=2)
    logger.info(f"Saved: {out}")

    return best


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="BTC/USDT")
    parser.add_argument("--model",  default="rf", choices=["xgb", "rf"])
    args = parser.parse_args()

    if not test_connection():
        sys.exit(1)

    if args.symbol == "all":
        for s in SYMBOLS:
            optimize(s, args.model)
    else:
        optimize(args.symbol, args.model)
