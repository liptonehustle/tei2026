# TEI2026 — AI Trading Data Platform
# Project Context File (Upload this at the start of every new chat)

---

## HOW TO USE THIS FILE

Upload this file and say:
> "Lanjutkan project AI trading platform saya. Baca context file dan lanjut dari checkpoint terakhir."

---

## ENVIRONMENT

| Item | Value |
|------|-------|
| OS | Windows |
| Python | 3.14 |
| Project path | C:\Users\PC\Documents\projects\ai-trading-platform |
| PostgreSQL port | 5433 (conflict dengan local PostgreSQL) |
| Redis port | 6379 |

## CREDENTIALS (.env)

```
POSTGRES_USER=tei_user
POSTGRES_PASSWORD=TEI@2026
POSTGRES_DB=tei2026
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=TEI@2026
PGADMIN_EMAIL=admin@tei2026.com
PGADMIN_PASSWORD=TEI@2026
```

---

## KNOWN ISSUES & FIXES

| Issue | Fix |
|-------|-----|
| Password TEI@2026 breaks URL string | Use psycopg2 params separately, NEVER connection URL |
| Binance blocked in Indonesia | Use Bybit instead |
| pandas-ta fails on Python 3.14 (numba) | Use `ta` library instead |
| PostgreSQL port conflict | Docker mapped to 5433:5432 |
| PowerShell `<` redirect not supported | Use `docker cp` + `docker exec` |
| `fatal: bad revision HEAD` | git not initialized — not harmful |
| Decimal type from PostgreSQL | Cast with pd.to_numeric() after DB fetch |

---

## TECH STACK

| Layer | Tool |
|-------|------|
| Language | Python 3.14 |
| Database | PostgreSQL (Docker, port 5433) |
| Message Queue | Redis (Docker, port 6379) |
| ML Libraries | scikit-learn, xgboost, ta, pandas, numpy |
| AI Reasoning | Ollama (local LLM) |
| Containers | Docker |
| Workflow | APScheduler |
| Dashboard | Grafana or Streamlit (Phase 7) |

---

## SYSTEM ARCHITECTURE

```
Bybit Exchange API
↓
Data Collector — every 5m (data_ingestion/scheduler.py)
↓
Redis queue: raw:market_data
↓
Indicator Engine (data_processing/indicator_engine.py)
↓
PostgreSQL (port 5433)
├── market_data     ← 130k+ rows (1m + 5m)
├── indicators      ← 8,600+ rows (5m)
├── predictions     ← RF model output
├── trade_decisions ← (Phase 6)
└── trades          ← (Phase 7)
↓
RandomForest Model (rf_BTCUSDT/ETHUSDT/BNBUSDT_v20260319)
↓
Decision Engine + Ollama (Phase 6 — NEXT)
↓
Risk Guard Module (1% risk, max 3 trades, 5% daily loss)
↓
Execution Engine (Phase 7)
```

---

## FOLDER STRUCTURE

```
ai-trading-platform/
├── config.py
├── check_setup.py
├── requirements.txt
├── requirements.lock
├── docker-compose.yml
├── .env
│
├── data_ingestion/
│   ├── collector.py          ← Bybit, TIMEFRAME="5m"
│   ├── scheduler.py          ← every 1 min (collects 5m candles)
│   ├── historical.py         ← backfill (--timeframe 5m)
│   ├── historical_multi.py   ← backfill 5m + 15m sekaligus
│   └── verify.py
│
├── data_processing/
│   ├── indicator_engine.py   ← TIMEFRAME="5m"
│   └── verify.py             ← TIMEFRAME="5m"
│
├── database/
│   ├── db.py                 ← params terpisah (bukan URL)
│   ├── queries.py            ← default timeframe="5m"
│   ├── monitor.py
│   └── migrations/001_init.sql
│
├── ml_models/
│   ├── features.py           ← default timeframe="5m"
│   ├── trainer.py            ← TIMEFRAME="5m"
│   ├── predictor.py          ← TIMEFRAME="5m", default model="rf"
│   └── verify.py             ← MODEL_TYPE="rf"
│
├── backtesting/
│   ├── engine.py             ← TIMEFRAME="5m", default model="rf"
│   │                            PROB_THRESHOLD=0.70
│   │                            STOP_LOSS_PCT=0.008
│   │                            TAKE_PROFIT_PCT=0.020
│   │                            MAX_HOLD=60
│   └── optimizer.py          ← TIMEFRAME="5m", default model="rf"
│
├── decision_engine/          ← Phase 6 (NEXT)
├── execution_engine/         ← Phase 7
│   └── risk_manager.py
└── docs/
    ├── backtest_results/     ← JSON hasil backtest tersimpan di sini
    └── prompts/
        └── decision_prompt.txt
```

---

## ML MODEL STATUS

| Symbol | Model | Version | AUC | Timeframe |
|--------|-------|---------|-----|-----------|
| BTC/USDT | RandomForest | rf_BTCUSDT_v20260319_1019 | 0.594 | 5m |
| ETH/USDT | RandomForest | rf_ETHUSDT_v20260319_1019 | 0.609 | 5m |
| BNB/USDT | RandomForest | rf_BNBUSDT_v20260319_1019 | 0.616 | 5m |

Saved di: `ml_models/saved/`

---

## BACKTEST RESULTS (Phase 5.5 — RF model, optimized params)

| Symbol | Sharpe | Return | Win Rate | Max DD | Trades |
|--------|--------|--------|----------|--------|--------|
| BTC/USDT | 5.41 | +81.9% | 53.5% | -30.6% | 486 |
| ETH/USDT | 0.24 | +42.9% | 47.8% | -33.0% | 358 |
| BNB/USDT | 5.08 | +80.0% | 56.8% | -32.1% | 458 |
| **Portfolio** | **3.58** | **+68.3%** | - | - | - |

**Strategy params (engine.py):**
- PROB_THRESHOLD = 0.70
- STOP_LOSS_PCT = 0.008
- TAKE_PROFIT_PCT = 0.020
- MAX_HOLD_CANDLES = 60
- FEE_PCT = 0.001

---

## OLLAMA PROMPT TEMPLATE

```
Given the following market data, produce a trading decision.

Indicators: {indicators_json}
ML Prediction: prob_up={prob_up}, prob_down={prob_down}
Risk Rules: {risk_rules_json}

Respond ONLY with a valid JSON object. No explanation. Format:
{
  "action": "buy" | "sell" | "hold",
  "entry_price": float,
  "stop_loss": float,
  "take_profit": float,
  "confidence": float (0.0 to 1.0),
  "reasoning": "one sentence max"
}
```

---

## RISK MANAGEMENT RULES

Enforced inside `execution_engine/risk_manager.py`:
- Max risk per trade: 1% of account
- Max open trades: 3
- Max daily loss: 5% of account
- No order bypasses risk_manager.py

---

## DEVELOPMENT ROADMAP

| Phase | Name | Status |
|-------|------|--------|
| 1 | Setup environment | ✅ Done |
| 2 | Data collector (Bybit, 5m) | ✅ Done |
| 3 | Database pipeline | ✅ Done |
| 4 | Indicator engine (5m) | ✅ Done |
| 5 | Machine learning (RF, 5m) | ✅ Done |
| 5.5 | Backtesting & validation | ✅ Done — Sharpe 3.58 |
| 6 | AI decision engine (Ollama) | ⬜ NEXT |
| 7 | Automated trading (live) | ⬜ |

**Rule**: Do NOT proceed to Phase 7 until Phase 6 backtest juga positif.

---

## DATA STATUS

| Symbol | 1m candles | 5m candles | 5m indicators |
|--------|-----------|-----------|---------------|
| BTC/USDT | 43,252 | 8,650+ | 8,600+ |
| ETH/USDT | 43,257 | 8,650+ | 8,600+ |
| BNB/USDT | 43,257 | 8,650+ | 8,600+ |

---

## TERMINAL SETUP (jalankan setiap mulai kerja)

```powershell
# Terminal 1 — Data collector
python -m data_ingestion.scheduler

# Terminal 2 — Indicator engine
python -m data_processing.indicator_engine --mode scheduler

# Terminal 3 — Development / testing
python -m database.monitor    # cek status DB
python -m ml_models.verify    # cek ML predictions
```

---

## CURRENT CHECKPOINT

**Last completed:** Phase 5.5 — Backtesting (Portfolio Sharpe 3.58 ✅)
**Currently working on:** Phase 6 — AI Decision Engine (Ollama)
**Next task:** Build decision_engine/ yang combine ML predictions + Ollama LLM

### Notes for next session:
- Ollama harus sudah terinstall di Windows: https://ollama.com
- Pull model dulu: `ollama pull llama3`
- Ollama berjalan di: http://localhost:11434
- Decision engine harus output structured JSON (lihat prompt template di atas)
- Setelah Phase 6 selesai — backtest ulang dengan decision engine aktif

---

## HOW TO ASK CLAUDE FOR HELP

Setelah upload file ini:
- "Lanjut Phase 6 — AI Decision Engine"
- "Ada error di [file], ini outputnya: ..."
- "Review code decision_engine/"
- "Update checkpoint setelah Phase 6 selesai"

---

*Last updated: Phase 5.5 complete — Backtesting passed (Sharpe 3.58)*