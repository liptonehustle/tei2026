"""
decision_engine/fetcher.py
Ambil latest indicators + ML predictions dari PostgreSQL untuk decision engine.
"""

import pandas as pd
from database.db import DB
from ml_models.predictor import predict_latest

SYMBOLS   = ["BTC/USDT", "ETH/USDT", "BNB/USDT"]   # format sesuai DB
TIMEFRAME = "5m"

# Map symbol DB -> format ML model (tanpa slash)
SYMBOL_TO_MODEL = {
    "BTC/USDT": "BTCUSDT",
    "ETH/USDT": "ETHUSDT",
    "BNB/USDT": "BNBUSDT",
}


def fetch_latest_indicators(symbol: str, timeframe: str = TIMEFRAME) -> dict | None:
    """
    Ambil baris terakhir dari tabel indicators untuk symbol & timeframe tertentu.
    Return dict of indicator values, atau None kalau kosong.
    """
    query = """
        SELECT *
        FROM indicators
        WHERE symbol = %s AND timeframe = %s
        ORDER BY timestamp DESC
        LIMIT 1
    """
    with DB() as (conn, cur):
        cur.execute(query, (symbol, timeframe))
        cols = [desc[0] for desc in cur.description]
        row  = cur.fetchone()

    if row is None:
        return None

    result = dict(zip(cols, row))

    # Cast Decimal -> float supaya JSON-serializable
    for k, v in result.items():
        try:
            result[k] = float(v)
        except (TypeError, ValueError):
            pass

    return result


def fetch_ml_prediction(symbol: str, timeframe: str = TIMEFRAME) -> dict | None:
    """
    Jalankan ML predictor untuk mendapatkan prob_up dan prob_down terbaru.
    symbol harus dalam format ML (BTCUSDT), bukan format DB (BTC/USDT).
    """
    ml_symbol = SYMBOL_TO_MODEL.get(symbol, symbol)
    try:
        result = predict_latest(symbol=ml_symbol, timeframe=timeframe, model_type="rf")
        if result is None:
            return None
        return {
            "prob_up":         round(float(result.get("prob_up", 0)), 4),
            "prob_down":       round(float(result.get("prob_down", 0)), 4),
            "predicted_label": result.get("predicted_label", "unknown"),
        }
    except Exception as e:
        print(f"[fetcher] ML prediction error untuk {symbol}: {e}")
        return None


def fetch_context(symbol: str, timeframe: str = TIMEFRAME) -> dict | None:
    """
    Gabungkan indicators + ML prediction jadi satu context dict.
    Return None kalau salah satu tidak tersedia.
    """
    indicators = fetch_latest_indicators(symbol, timeframe)
    if indicators is None:
        print(f"[fetcher] Tidak ada data indicators untuk {symbol}")
        return None

    ml = fetch_ml_prediction(symbol, timeframe)
    if ml is None:
        print(f"[fetcher] Tidak ada ML prediction untuk {symbol}")
        return None

    return {
        "symbol":    symbol,
        "timeframe": timeframe,
        "timestamp": str(indicators.get("timestamp", "")),
        "close":     indicators.get("close", 0),
        "indicators": {
            k: v for k, v in indicators.items()
            if k not in ("id", "symbol", "timeframe", "timestamp", "close", "created_at")
        },
        "ml_prediction": ml,
    }


if __name__ == "__main__":
    import json
    for sym in SYMBOLS:
        print(f"\n{'='*50}")
        print(f"Symbol: {sym}")
        ctx = fetch_context(sym)
        if ctx:
            print(json.dumps(ctx, indent=2, default=str))
        else:
            print("  [!] Context tidak tersedia")