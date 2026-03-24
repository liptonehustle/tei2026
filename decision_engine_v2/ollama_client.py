"""
decision_engine/ollama_client.py
Kirim context ke Ollama (llama3) dan parse structured JSON decision.
"""

import json
import re
import requests

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3"
TIMEOUT      = 60  # seconds

PROMPT_TEMPLATE = """You are a professional cryptocurrency trading assistant.
Analyze the market data below and produce a trading decision.

Symbol: {symbol}
Timestamp: {timestamp}
Current Close Price: {close}

Key Indicators:
{indicators_text}

ML Model Prediction:
- prob_up   = {prob_up}   (probability price goes UP next candle)
- prob_down = {prob_down} (probability price goes DOWN next candle)
- ML signal = {predicted_label}

Risk Rules:
- Max risk per trade : 1% of account
- Max open trades    : 3
- Max daily loss     : 5%
- Stop loss          : ~0.8% from entry
- Take profit        : ~2.0% from entry

Respond ONLY with a valid JSON object. No explanation, no markdown, no extra text.
{{
  "action"      : "buy" | "sell" | "hold",
  "entry_price" : float,
  "stop_loss"   : float,
  "take_profit" : float,
  "confidence"  : float (0.0 to 1.0),
  "reasoning"   : "one sentence max"
}}"""


def _build_indicators_text(indicators: dict) -> str:
    """Format dict indicators jadi string ringkas untuk prompt."""
    lines = []
    # Nama kolom sesuai schema DB
    priority = [
        "rsi_14", "macd", "macd_signal", "macd_hist",
        "ema_20", "ema_50", "bb_upper", "bb_lower", "bb_middle",
        "atr", "adx",
    ]
    shown = set()
    for key in priority:
        if key in indicators:
            lines.append(f"  {key:<15} = {indicators[key]:.4f}")
            shown.add(key)
    for key, val in indicators.items():
        if key not in shown:
            try:
                lines.append(f"  {key:<15} = {float(val):.4f}")
            except (TypeError, ValueError):
                lines.append(f"  {key:<15} = {val}")
    return "\n".join(lines)


def _extract_json(text: str) -> dict | None:
    """
    Cari blok JSON pertama dalam response teks.
    Robust terhadap markdown code block atau teks tambahan.
    """
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    match = re.search(r'\{.*?\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def ask_ollama(context: dict) -> dict | None:
    """
    Kirim context ke Ollama llama3, return parsed decision dict.
    Return None jika gagal (timeout, parse error, dll).
    """
    indicators_text = _build_indicators_text(context.get("indicators", {}))
    ml = context.get("ml_prediction", {})

    prompt = PROMPT_TEMPLATE.format(
        symbol          = context.get("symbol", ""),
        timestamp       = context.get("timestamp", ""),
        close           = context.get("close", 0),
        indicators_text = indicators_text,
        prob_up         = ml.get("prob_up", 0),
        prob_down       = ml.get("prob_down", 0),
        predicted_label = ml.get("predicted_label", "unknown"),
    )

    payload = {
        "model":  OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=TIMEOUT)
        resp.raise_for_status()
        raw_text = resp.json().get("response", "")
    except requests.exceptions.Timeout:
        print(f"[ollama_client] Timeout setelah {TIMEOUT}s untuk {context.get('symbol')}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[ollama_client] Request error: {e}")
        return None

    decision = _extract_json(raw_text)
    if decision is None:
        print(f"[ollama_client] Gagal parse JSON dari response:\n{raw_text[:300]}")
        return None

    required = {"action", "entry_price", "stop_loss", "take_profit", "confidence", "reasoning"}
    missing = required - decision.keys()
    if missing:
        print(f"[ollama_client] Field hilang: {missing}")
        return None

    try:
        decision["entry_price"] = float(decision["entry_price"])
        decision["stop_loss"]   = float(decision["stop_loss"])
        decision["take_profit"] = float(decision["take_profit"])
        decision["confidence"]  = float(decision["confidence"])
        decision["action"]      = str(decision["action"]).lower().strip()
    except (TypeError, ValueError) as e:
        print(f"[ollama_client] Type conversion error: {e}")
        return None

    if decision["action"] not in ("buy", "sell", "hold"):
        print(f"[ollama_client] Action tidak valid: {decision['action']}")
        return None

    return decision