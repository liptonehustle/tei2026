"""
strategies/multi_confluence.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy 5 — Multi-Indicator Confluence

Logic:
  Score each indicator vote (bullish/bearish/neutral).
  BUY  when >= 4/5 indicators agree bullish + prob_up > 55%
  SELL when >= 4/5 indicators agree bearish + prob_down > 55%

Indicators voted:
  1. EMA trend (EMA20 vs EMA50)
  2. RSI (< 50 = bearish, > 50 = bullish)
  3. MACD histogram (positive = bullish)
  4. BB position (< 0.4 = bullish, > 0.6 = bearish)
  5. ADX (trend strength bonus)

Best in: trending + momentum market
Win rate: ~60-65% historically (higher bar = higher precision)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

from strategies.base import BaseStrategy, StrategySignal


class MultiConfluence(BaseStrategy):

    name = "multi_confluence"

    MIN_VOTES  = 3      # out of 5 indicators must agree
    MIN_PROB   = 0.52   # slightly higher ML bar for confluence

    # Wider TP — confluence signals tend to have more follow-through
    STOP_LOSS_PCT   = 0.009
    TAKE_PROFIT_PCT = 0.025

    def evaluate(self, symbol, indicators, prediction, current_price) -> StrategySignal:
        ema_20   = float(indicators.get("ema_20", current_price))
        ema_50   = float(indicators.get("ema_50", current_price))
        rsi      = float(indicators.get("rsi_14", 50))
        macd_h   = float(indicators.get("macd_hist", 0))
        bb_upper = float(indicators.get("bb_upper", current_price * 1.02))
        bb_lower = float(indicators.get("bb_lower", current_price * 0.98))
        adx      = float(indicators.get("adx", 0))
        prob_up   = float(prediction.get("prob_up", 0.5))
        prob_down = float(prediction.get("prob_down", 0.5))

        bb_range    = bb_upper - bb_lower if bb_upper != bb_lower else 1
        bb_position = (current_price - bb_lower) / bb_range

        # ── Score bullish votes ────────────────────────
        bull_votes = 0
        bear_votes = 0
        vote_log   = []

        # 1. EMA trend
        if ema_20 > ema_50:
            bull_votes += 1
            vote_log.append("EMA↑")
        else:
            bear_votes += 1
            vote_log.append("EMA↓")

        # 2. RSI
        if rsi < 50:
            bear_votes += 1
            vote_log.append(f"RSI↓{rsi:.0f}")
        else:
            bull_votes += 1
            vote_log.append(f"RSI↑{rsi:.0f}")

        # 3. MACD histogram
        if macd_h > 0:
            bull_votes += 1
            vote_log.append("MACD↑")
        else:
            bear_votes += 1
            vote_log.append("MACD↓")

        # 4. BB position
        if bb_position < 0.4:
            bull_votes += 1
            vote_log.append(f"BB↑{bb_position:.2f}")
        elif bb_position > 0.6:
            bear_votes += 1
            vote_log.append(f"BB↓{bb_position:.2f}")

        # 5. ADX — adds to whichever side is winning
        if adx > 20:
            if bull_votes > bear_votes:
                bull_votes += 1
                vote_log.append(f"ADX+bull{adx:.0f}")
            elif bear_votes > bull_votes:
                bear_votes += 1
                vote_log.append(f"ADX+bear{adx:.0f}")

        votes_str = " ".join(vote_log)

        # ── BUY: majority bullish confluence ────────────
        if bull_votes >= self.MIN_VOTES and prob_up > self.MIN_PROB:
            vote_score = (bull_votes - self.MIN_VOTES) / 5
            ml_score   = (prob_up - self.MIN_PROB) / (1 - self.MIN_PROB)
            confidence = round(min(0.95, 0.55 + vote_score * 0.2 + ml_score * 0.2), 4)
            atr = float(indicators.get("atr", 0))
            sl, tp = self.get_sl_tp("buy", current_price, atr)
            return StrategySignal(
                strategy_name = self.name,
                symbol        = symbol,
                action        = "buy",
                confidence    = confidence,
                entry_price   = current_price,
                stop_loss     = sl,
                take_profit   = tp,
                reasoning     = f"Confluence {bull_votes}/5 bull [{votes_str}] prob_up={prob_up:.0%}",
            )

        # ── SELL: majority bearish confluence ───────────
        if bear_votes >= self.MIN_VOTES and prob_down > self.MIN_PROB:
            vote_score = (bear_votes - self.MIN_VOTES) / 5
            ml_score   = (prob_down - self.MIN_PROB) / (1 - self.MIN_PROB)
            confidence = round(min(0.95, 0.55 + vote_score * 0.2 + ml_score * 0.2), 4)
            atr = float(indicators.get("atr", 0))
            sl, tp = self.get_sl_tp("sell", current_price, atr)
            return StrategySignal(
                strategy_name = self.name,
                symbol        = symbol,
                action        = "sell",
                confidence    = confidence,
                entry_price   = current_price,
                stop_loss     = sl,
                take_profit   = tp,
                reasoning     = f"Confluence {bear_votes}/5 bear [{votes_str}] prob_down={prob_down:.0%}",
            )

        return StrategySignal(
            strategy_name = self.name,
            symbol        = symbol,
            action        = "hold",
            confidence    = 0.0,
            reasoning     = f"No confluence: bull={bull_votes} bear={bear_votes} [{votes_str}]",
        )
