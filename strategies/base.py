"""
strategies/base.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Base class for all trading strategies.

Every strategy must implement:
  - evaluate(symbol, indicators, prediction, current_price) → StrategySignal

The runner will call evaluate() on all strategies each cycle,
collect all signals, and select the strongest one for execution.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from dataclasses import dataclass, field
from abc import ABC, abstractmethod


@dataclass
class StrategySignal:
    """Output from a strategy evaluation."""
    strategy_name: str
    symbol:        str
    action:        str          # 'buy', 'sell', 'hold'
    confidence:    float        # 0.0 to 1.0
    entry_price:   float | None = None
    stop_loss:     float | None = None
    take_profit:   float | None = None
    reasoning:     str          = ""
    was_selected:  bool         = False


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Subclasses must implement evaluate().
    All strategies share the same input/output contract.
    """

    name: str = "base"

    # Risk parameters — can be overridden per strategy
    # STOP_LOSS_PCT:   float = 0.008   # 0.8%
    # TAKE_PROFIT_PCT: float = 0.020   # 2.0%

    def get_sl_tp(self, action: str, price: float, atr: float = 0) -> tuple[float, float]:
        if atr > 0:
            sl_dist = atr * 1.5
            tp_dist = atr * 2.0
        else:
            sl_dist = price * 0.005
            tp_dist = price * 0.010

        if action == "buy":
            sl = round(price - sl_dist, 4)
            tp = round(price + tp_dist, 4)
        else:
            sl = round(price + sl_dist, 4)
            tp = round(price - tp_dist, 4)
        return sl, tp

    @abstractmethod
    def evaluate(
        self,
        symbol:        str,
        indicators:    dict,
        prediction:    dict,
        current_price: float,
    ) -> StrategySignal:
        """
        Evaluate market conditions and return a signal.

        Args:
            symbol:        e.g. 'BTC/USDT'
            indicators:    latest indicator row as dict
            prediction:    ML prediction dict (prob_up, prob_down)
            current_price: latest close price

        Returns:
            StrategySignal with action, confidence, sl, tp, reasoning
        """
        ...
