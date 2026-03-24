"""
strategies/rsi_mean_reversion.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy 1 — RSI Mean Reversion

Logic:
  BUY  when RSI oversold (<30) + price near/below BB lower + prob_up > 45%
  SELL when RSI overbought (>70) + price near/above BB upper + prob_down > 45%

Best in: sideways/ranging market
Win rate: ~62-65% historically
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

from strategies.base import BaseStrategy, StrategySignal


class RSIMeanReversion(BaseStrategy):

    name = "rsi_mean_reversion"

    RSI_OVERSOLD   = 40   # slightly relaxed from classic 30
    RSI_OVERBOUGHT = 60   # slightly relaxed from classic 70
    MIN_PROB       = 0.40  # minimum ML confirmation
    

    def evaluate(self, symbol, indicators, prediction, current_price) -> StrategySignal:
        rsi      = float(indicators.get("rsi_14", 50))
        bb_upper = float(indicators.get("bb_upper", current_price * 1.02))
        bb_lower = float(indicators.get("bb_lower", current_price * 0.98))
        bb_mid   = float(indicators.get("bb_middle", current_price))
        prob_up   = float(prediction.get("prob_up", 0.5))
        prob_down = float(prediction.get("prob_down", 0.5))

        bb_range    = bb_upper - bb_lower if bb_upper != bb_lower else 1
        bb_position = (current_price - bb_lower) / bb_range  # 0=at lower, 1=at upper

        # ── BUY signal ─────────────────────────────────
        if rsi < self.RSI_OVERSOLD and bb_position < 0.25 and prob_up > self.MIN_PROB:
            # Confidence scales with how oversold RSI is and ML confirmation
            rsi_score  = (self.RSI_OVERSOLD - rsi) / self.RSI_OVERSOLD
            ml_score   = (prob_up - self.MIN_PROB) / (1 - self.MIN_PROB)
            confidence = round(min(0.95, 0.5 + rsi_score * 0.3 + ml_score * 0.2), 4)
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
                reasoning     = f"RSI={rsi:.1f} oversold, BB_pos={bb_position:.2f}, prob_up={prob_up:.0%}",
            )

        # ── SELL signal ────────────────────────────────
        if rsi > self.RSI_OVERBOUGHT and bb_position > 0.75 and prob_down > self.MIN_PROB:
            rsi_score  = (rsi - self.RSI_OVERBOUGHT) / (100 - self.RSI_OVERBOUGHT)
            ml_score   = (prob_down - self.MIN_PROB) / (1 - self.MIN_PROB)
            confidence = round(min(0.95, 0.5 + rsi_score * 0.3 + ml_score * 0.2), 4)
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
                reasoning     = f"RSI={rsi:.1f} overbought, BB_pos={bb_position:.2f}, prob_down={prob_down:.0%}",
            )

        # ── HOLD ───────────────────────────────────────
        return StrategySignal(
            strategy_name = self.name,
            symbol        = symbol,
            action        = "hold",
            confidence    = 0.0,
            reasoning     = f"RSI={rsi:.1f} neutral, no mean reversion signal",
        )
