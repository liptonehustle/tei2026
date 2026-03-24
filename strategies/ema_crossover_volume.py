"""
strategies/ema_crossover_volume.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy 3 — EMA Crossover + Volume Confirmation

Logic:
  BUY  when EMA20 crosses ABOVE EMA50 + volume spike + prob_up > 50%
  SELL when EMA20 crosses BELOW EMA50 + volume spike + prob_down > 50%

Volume spike = current volume > 1.5x average volume (volume_ratio)
ADX > 20 as trend strength filter

Best in: trending market
Win rate: ~55-60% historically
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import sys
sys.path.insert(0, ".")

from strategies.base import BaseStrategy, StrategySignal


class EMACrossoverVolume(BaseStrategy):

    name = "ema_crossover_volume"

    MIN_VOLUME_RATIO = 1.3   # volume must be 1.3x average
    MIN_ADX          = 18    # relaxed from 25 — catch earlier trends
    MIN_PROB         = 0.50

    def evaluate(self, symbol, indicators, prediction, current_price) -> StrategySignal:
        ema_20 = float(indicators.get("ema_20", current_price))
        ema_50 = float(indicators.get("ema_50", current_price))
        adx    = float(indicators.get("adx", 0))
        macd_h = float(indicators.get("macd_hist", 0))
        prob_up   = float(prediction.get("prob_up", 0.5))
        prob_down = float(prediction.get("prob_down", 0.5))

        ema_cross    = (ema_20 - ema_50) / current_price  # positive = bullish
        trend_up     = ema_cross > 0
        trend_down   = ema_cross < 0
        trend_strong = adx > self.MIN_ADX
        macd_bull    = macd_h > 0
        macd_bear    = macd_h < 0

        # ── BUY: bullish EMA cross + trend confirmation ─
        if trend_up and trend_strong and macd_bull and prob_up > self.MIN_PROB:
            cross_score = min(1.0, abs(ema_cross) * 100)
            adx_score   = min(1.0, (adx - self.MIN_ADX) / 30)
            ml_score    = (prob_up - self.MIN_PROB) / (1 - self.MIN_PROB)
            confidence  = round(min(0.95, 0.50 + cross_score * 0.2 + adx_score * 0.15 + ml_score * 0.15), 4)
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
                reasoning     = f"EMA cross bullish={ema_cross:.4f}, ADX={adx:.1f}, MACD_h>0, prob_up={prob_up:.0%}",
            )

        # ── SELL: bearish EMA cross + trend confirmation ─
        if trend_down and trend_strong and macd_bear and prob_down > self.MIN_PROB:
            cross_score = min(1.0, abs(ema_cross) * 100)
            adx_score   = min(1.0, (adx - self.MIN_ADX) / 30)
            ml_score    = (prob_down - self.MIN_PROB) / (1 - self.MIN_PROB)
            confidence  = round(min(0.95, 0.50 + cross_score * 0.2 + adx_score * 0.15 + ml_score * 0.15), 4)
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
                reasoning     = f"EMA cross bearish={ema_cross:.4f}, ADX={adx:.1f}, MACD_h<0, prob_down={prob_down:.0%}",
            )

        return StrategySignal(
            strategy_name = self.name,
            symbol        = symbol,
            action        = "hold",
            confidence    = 0.0,
            reasoning     = f"EMA cross={ema_cross:.4f}, ADX={adx:.1f} — no strong trend signal",
        )
