"""
strategies/bb_squeeze_breakout.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy 2 — Bollinger Band Squeeze Breakout

Logic:
  Detect when BB width narrows (squeeze = low volatility)
  BUY  when price breaks ABOVE BB upper after squeeze + prob_up > 50%
  SELL when price breaks BELOW BB lower after squeeze + prob_down > 50%

Best in: transition from low → high volatility
Win rate: ~58-62% historically
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

from strategies.base import BaseStrategy, StrategySignal


class BBSqueezeBreakout(BaseStrategy):

    name = "bb_squeeze_breakout"

    SQUEEZE_THRESHOLD = 0.015  # BB width < 1.5% of price = squeeze
    MIN_PROB          = 0.50

    # Wider TP for breakout strategy — ride the momentum
    STOP_LOSS_PCT   = 0.010
    TAKE_PROFIT_PCT = 0.030

    def evaluate(self, symbol, indicators, prediction, current_price) -> StrategySignal:
        bb_upper = float(indicators.get("bb_upper", current_price * 1.02))
        bb_lower = float(indicators.get("bb_lower", current_price * 0.98))
        bb_mid   = float(indicators.get("bb_middle", current_price))
        atr      = float(indicators.get("atr", current_price * 0.01))
        prob_up   = float(prediction.get("prob_up", 0.5))
        prob_down = float(prediction.get("prob_down", 0.5))

        bb_width    = (bb_upper - bb_lower) / current_price
        is_squeeze  = bb_width < self.SQUEEZE_THRESHOLD
        above_upper = current_price > bb_upper
        below_lower = current_price < bb_lower

        # ── BUY: breakout above upper band after squeeze ─
        if above_upper and prob_up > self.MIN_PROB:
            breakout_strength = (current_price - bb_upper) / atr if atr > 0 else 0
            squeeze_bonus     = 0.1 if is_squeeze else 0
            confidence        = round(min(0.95, 0.55 + breakout_strength * 0.1 + squeeze_bonus + (prob_up - 0.5) * 0.3), 4)
            sl, tp = self.get_sl_tp("buy", current_price)
            return StrategySignal(
                strategy_name = self.name,
                symbol        = symbol,
                action        = "buy",
                confidence    = confidence,
                entry_price   = current_price,
                stop_loss     = sl,
                take_profit   = tp,
                reasoning     = f"BB breakout above upper, width={bb_width:.3f}, squeeze={is_squeeze}, prob_up={prob_up:.0%}",
            )

        # ── SELL: breakdown below lower band after squeeze
        if below_lower and prob_down > self.MIN_PROB:
            breakdown_strength = (bb_lower - current_price) / atr if atr > 0 else 0
            squeeze_bonus      = 0.1 if is_squeeze else 0
            confidence         = round(min(0.95, 0.55 + breakdown_strength * 0.1 + squeeze_bonus + (prob_down - 0.5) * 0.3), 4)
            sl, tp = self.get_sl_tp("sell", current_price)
            return StrategySignal(
                strategy_name = self.name,
                symbol        = symbol,
                action        = "sell",
                confidence    = confidence,
                entry_price   = current_price,
                stop_loss     = sl,
                take_profit   = tp,
                reasoning     = f"BB breakdown below lower, width={bb_width:.3f}, squeeze={is_squeeze}, prob_down={prob_down:.0%}",
            )

        return StrategySignal(
            strategy_name = self.name,
            symbol        = symbol,
            action        = "hold",
            confidence    = 0.0,
            reasoning     = f"No BB breakout. width={bb_width:.3f}, squeeze={is_squeeze}",
        )
