"""
decision_engine/prompt_builder.py
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Phase 6 — Prompt Builder

Builds structured prompts for the Ollama decision engine.
Combines indicators + ML predictions + risk context.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json

SYSTEM_PROMPT = """You are a crypto trading AI. Analyze market data and respond with JSON only. No explanations outside JSON."""


def build_decision_prompt(
    symbol: str,
    current_price: float,
    indicators: dict,
    prediction: dict,
    open_trades: int,
    daily_pnl: float,
    account_capital: float,
    strategy_signal=None,
) -> str:
    """Build compact prompt that fits within llama3 context window."""

    ind = {
        "ema_20":  round(float(indicators.get("ema_20", 0)), 2),
        "ema_50":  round(float(indicators.get("ema_50", 0)), 2),
        "rsi":     round(float(indicators.get("rsi_14", 0)), 1),
        "macd_h":  round(float(indicators.get("macd_hist", 0)), 6),
        "atr":     round(float(indicators.get("atr", 0)), 2),
        "adx":     round(float(indicators.get("adx", 0)), 1),
        "bb_up":   round(float(indicators.get("bb_upper", 0)), 2),
        "bb_lo":   round(float(indicators.get("bb_lower", 0)), 2),
    }

    trend  = "UP"   if ind["ema_20"] > ind["ema_50"] else "DOWN"
    rsi_s  = "OB"   if ind["rsi"] > 70 else "OS" if ind["rsi"] < 30 else "NEU"
    macd_s = "BULL" if ind["macd_h"] > 0 else "BEAR"
    adx_s  = "STRONG" if ind["adx"] > 25 else "WEAK"
    bb_s   = "ABOVE" if current_price > ind["bb_up"] else \
             "BELOW" if current_price < ind["bb_lo"] else "INSIDE"

    prob_up   = float(prediction.get("prob_up", 0))
    prob_down = float(prediction.get("prob_down", 0))

    sl_buy  = round(current_price * 0.992, 4)
    tp_buy  = round(current_price * 1.020, 4)
    sl_sell = round(current_price * 1.008, 4)
    tp_sell = round(current_price * 0.980, 4)
    # Strategy signal context
    if strategy_signal and strategy_signal.action != "hold":
        # Strip unicode arrows, truncate reasoning to 80 chars
        clean_reasoning = strategy_signal.reasoning.encode('ascii', 'ignore').decode()[:80]
        strategy_ctx = (
            f"STRATEGY_SIGNAL: {strategy_signal.strategy_name.upper()} "
            f"{strategy_signal.action.upper()} conf={strategy_signal.confidence:.0%} | "
            f"{clean_reasoning}"
        )
    else:
        strategy_ctx = "STRATEGY_SIGNAL: all strategies HOLD"

    prompt = f"""Trading signal for {symbol} at {current_price:.2f} USDT (5m chart):

INDICATORS: EMA_trend={trend} RSI={ind['rsi']}({rsi_s}) MACD={macd_s} ADX={ind['adx']}({adx_s}) BB={bb_s}
ML_PREDICTION: prob_up={prob_up:.0%} prob_down={prob_down:.0%}
RISK: open_trades={open_trades}/3 daily_pnl={daily_pnl:+.0f}USD
{strategy_ctx}

RULES:
- BUY if: prob_up>70% AND RSI<65 AND MACD=BULL AND ADX=STRONG → sl={sl_buy} tp={tp_buy}
- SELL if: prob_down>70% AND RSI>35 AND MACD=BEAR AND ADX=STRONG → sl={sl_sell} tp={tp_sell}
- HOLD if signals mixed or ADX=WEAK or open_trades>=3

Respond with JSON only:
{{"action":"buy/sell/hold","entry_price":null,"stop_loss":null,"take_profit":null,"confidence":0.0,"reasoning":"brief reason"}}"""

    return prompt