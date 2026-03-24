"""
decision_engine/engine.py
Orchestrator utama Phase 6:
  1. Fetch context (indicators + ML prediction)
  2. Kirim ke Ollama -> dapat raw decision
  3. Combine confidence: ML score + Ollama confidence
  4. Validasi via Risk Guard
  5. Simpan ke tabel trade_decisions
"""

import json
from datetime import datetime, timezone

from database.db import DB
from decision_engine.fetcher import fetch_context, SYMBOLS
from decision_engine.ollama_client import ask_ollama

# Threshold gabungan (ML prob + Ollama confidence)
ML_PROB_THRESHOLD     = 0.60
OLLAMA_CONF_THRESHOLD = 0.60
COMBINED_THRESHOLD    = 0.65

TIMEFRAME = "5m"


# ---------------------------------------------------------------------------
# Risk Guard
# ---------------------------------------------------------------------------

def _check_risk(action: str, symbol: str) -> tuple[bool, str]:
    if action == "hold":
        return True, "hold -- no risk check needed"

    with DB() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM trade_decisions WHERE status = 'open'")
        open_count = cur.fetchone()[0]
        if open_count >= 3:
            return False, f"Max open trades reached ({open_count}/3)"

        cur.execute(
            "SELECT COUNT(*) FROM trade_decisions WHERE symbol = %s AND status = 'open'",
            (symbol,)
        )
        symbol_open = cur.fetchone()[0]
        if symbol_open > 0:
            return False, f"Already have open trade for {symbol}"

    return True, "risk check passed"


# ---------------------------------------------------------------------------
# Combined confidence scoring
# ---------------------------------------------------------------------------

def _combined_confidence(ml: dict, action: str) -> float:
    if action == "hold":
        return 0.0
    return ml.get("prob_up", 0) if action == "buy" else ml.get("prob_down", 0)


def _is_confident_enough(ml: dict, ollama_decision: dict) -> tuple[bool, float]:
    action = ollama_decision.get("action", "hold")
    if action == "hold":
        return True, 0.0

    ml_score    = _combined_confidence(ml, action)
    ollama_conf = ollama_decision.get("confidence", 0.0)
    combined    = round((ml_score + ollama_conf) / 2, 4)

    passed = (
        ml_score    >= ML_PROB_THRESHOLD
        and ollama_conf >= OLLAMA_CONF_THRESHOLD
        and combined    >= COMBINED_THRESHOLD
    )
    return passed, combined


# ---------------------------------------------------------------------------
# DB persistence
# ---------------------------------------------------------------------------

def _save_decision(symbol: str, context: dict, ollama_decision: dict,
                   combined_score: float, risk_ok: bool, risk_reason: str) -> int | None:
    action       = ollama_decision.get("action", "hold")
    final_action = action if risk_ok else "hold"
    status       = "open" if final_action in ("buy", "sell") else "skipped"

    with DB() as (conn, cur):
        cur.execute("""
            INSERT INTO trade_decisions (
                symbol, timeframe, timestamp,
                action, entry_price, stop_loss, take_profit,
                ml_prob_up, ml_prob_down, ollama_confidence,
                combined_score, reasoning, risk_check_passed,
                risk_reason, status, raw_context, created_at
            ) VALUES (
                %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s
            )
            RETURNING id
        """, (
            symbol,
            TIMEFRAME,
            context.get("timestamp"),
            final_action,
            ollama_decision.get("entry_price"),
            ollama_decision.get("stop_loss"),
            ollama_decision.get("take_profit"),
            context["ml_prediction"].get("prob_up"),
            context["ml_prediction"].get("prob_down"),
            ollama_decision.get("confidence"),
            combined_score,
            ollama_decision.get("reasoning", ""),
            risk_ok,
            risk_reason,
            status,
            json.dumps(context, default=str),
            datetime.now(timezone.utc),
        ))
        row_id = cur.fetchone()[0]
    # commit otomatis dari DB.__exit__
    return row_id


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_decision_cycle(symbols: list[str] = None) -> list[dict]:
    if symbols is None:
        symbols = SYMBOLS

    results = []

    for symbol in symbols:
        print(f"\n{'─'*55}")
        print(f"[engine] Processing {symbol} @ {datetime.now().strftime('%H:%M:%S')}")

        # 1. Fetch context
        context = fetch_context(symbol)
        if context is None:
            print(f"[engine] Skip {symbol} -- context tidak tersedia")
            results.append({"symbol": symbol, "status": "no_context"})
            continue

        # 2. Ask Ollama
        print(f"[engine] Sending to Ollama ({symbol})...")
        ollama_dec = ask_ollama(context)
        if ollama_dec is None:
            print(f"[engine] Skip {symbol} -- Ollama gagal")
            results.append({"symbol": symbol, "status": "ollama_error"})
            continue

        action = ollama_dec.get("action", "hold")
        print(f"[engine] Ollama: action={action}, "
              f"confidence={ollama_dec.get('confidence')}, "
              f"reasoning={ollama_dec.get('reasoning')}")

        # 3. Combined confidence check
        conf_ok, combined_score = _is_confident_enough(context["ml_prediction"], ollama_dec)
        if not conf_ok:
            print(f"[engine] Confidence tidak cukup (combined={combined_score}) -> override ke hold")
            ollama_dec["action"] = "hold"
            action = "hold"

        # 4. Risk Guard
        risk_ok, risk_reason = _check_risk(action, symbol)
        if not risk_ok:
            print(f"[engine] Risk check FAILED: {risk_reason}")

        # 5. Simpan ke DB
        row_id = _save_decision(
            symbol, context, ollama_dec,
            combined_score, risk_ok, risk_reason
        )
        print(f"[engine] Saved -> trade_decisions.id={row_id}, "
              f"final_action={ollama_dec['action']}, combined={combined_score}")

        results.append({
            "symbol":         symbol,
            "action":         ollama_dec["action"],
            "entry_price":    ollama_dec.get("entry_price"),
            "stop_loss":      ollama_dec.get("stop_loss"),
            "take_profit":    ollama_dec.get("take_profit"),
            "combined_score": combined_score,
            "risk_ok":        risk_ok,
            "db_id":          row_id,
            "status":         "ok",
        })

    return results


if __name__ == "__main__":
    print("=" * 55)
    print("  TEI2026 -- Decision Engine (Phase 6)")
    print("  Mode: Ollama + ML Combined")
    print("=" * 55)

    results = run_decision_cycle()

    print(f"\n{'='*55}")
    print("SUMMARY:")
    for r in results:
        if r.get("status") == "ok":
            print(f"  {r['symbol']:<10} action={r['action']:<5} "
                  f"score={r.get('combined_score', 0):.3f}  "
                  f"risk={'OK' if r.get('risk_ok') else 'BLOCKED'}  "
                  f"db_id={r.get('db_id')}")
        else:
            print(f"  {r['symbol']:<10} status={r.get('status')}")
