"""
decision_engine/verify.py
Test semua komponen Phase 6 step-by-step.

Run:
    python -m decision_engine.verify
"""

import json
import sys


def test_ollama_connection():
    print("\n[1/4] Test koneksi Ollama...")
    import requests
    try:
        resp   = requests.get("http://localhost:11434/api/tags", timeout=5)
        models = [m["name"] for m in resp.json().get("models", [])]
        print(f"  OK  Ollama connected. Models tersedia: {models}")
        if not any("llama3" in m for m in models):
            print("  WARN  llama3 tidak ditemukan! Jalankan: ollama pull llama3")
            return False
        return True
    except Exception as e:
        print(f"  FAIL  Gagal konek ke Ollama: {e}")
        print("        Pastikan Ollama berjalan: ollama serve")
        return False


def test_fetcher():
    print("\n[2/4] Test fetcher (indicators + ML)...")
    from decision_engine.fetcher import fetch_context
    ctx = fetch_context("BTCUSDT")
    if ctx is None:
        print("  FAIL  fetch_context gagal -- cek DB dan ML model")
        return False, None
    print(f"  OK   Context tersedia")
    print(f"       timestamp    : {ctx['timestamp']}")
    print(f"       close        : {ctx['close']}")
    print(f"       indicators   : {len(ctx['indicators'])} kolom")
    print(f"       ml_prob_up   : {ctx['ml_prediction']['prob_up']}")
    print(f"       ml_prob_down : {ctx['ml_prediction']['prob_down']}")
    return True, ctx


def test_ollama_decision(ctx: dict):
    print("\n[3/4] Test Ollama decision...")
    from decision_engine.ollama_client import ask_ollama
    dec = ask_ollama(ctx)
    if dec is None:
        print("  FAIL  Ollama gagal return decision")
        return False, None
    print(f"  OK   Decision diterima")
    print(f"       action       : {dec['action']}")
    print(f"       entry_price  : {dec['entry_price']}")
    print(f"       stop_loss    : {dec['stop_loss']}")
    print(f"       take_profit  : {dec['take_profit']}")
    print(f"       confidence   : {dec['confidence']}")
    print(f"       reasoning    : {dec['reasoning']}")
    return True, dec


def test_full_cycle():
    print("\n[4/4] Test full decision cycle (1 symbol)...")
    from decision_engine.engine import run_decision_cycle
    results = run_decision_cycle(symbols=["BTCUSDT"])
    r = results[0]
    if r.get("status") != "ok":
        print(f"  FAIL  Full cycle gagal: {r.get('status')}")
        return False
    print(f"  OK   Full cycle selesai")
    print(f"       action        : {r['action']}")
    print(f"       combined_score: {r.get('combined_score')}")
    print(f"       risk_ok       : {r.get('risk_ok')}")
    print(f"       db_id         : {r.get('db_id')}")
    return True


if __name__ == "__main__":
    print("=" * 55)
    print("  TEI2026 -- Phase 6 Verification")
    print("=" * 55)

    passed = 0
    total  = 4

    ok1 = test_ollama_connection()
    if ok1: passed += 1

    ok2, ctx = test_fetcher()
    if ok2: passed += 1

    ok3, dec = False, None
    if ok2 and ctx:
        ok3, dec = test_ollama_decision(ctx)
        if ok3: passed += 1

    ok4 = False
    if ok3:
        ok4 = test_full_cycle()
        if ok4: passed += 1

    print(f"\n{'='*55}")
    print(f"RESULT: {passed}/{total} tests passed")
    if passed == total:
        print("Phase 6 READY -- semua komponen OK!")
        print("Jalankan: python -m decision_engine.scheduler")
    else:
        print("Ada komponen yang perlu diperbaiki (lihat output di atas)")
    print("=" * 55)

    sys.exit(0 if passed == total else 1)
