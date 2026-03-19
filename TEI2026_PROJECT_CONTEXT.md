# TEI2026 — AI Trading Data Platform
# Project Context File (Upload this at the start of every new chat)

---

## HOW TO USE THIS FILE

Upload this file and say:
> "I'm continuing my AI trading data platform project. Please read the context file and help me continue from the current checkpoint."

Update the CHECKPOINT section every time you finish a phase.

---

## PROJECT GOAL

Build an AI-powered data engineering pipeline for market trading (crypto, forex, stocks) as a **Data Engineer portfolio project**.

Goals:
- Automated market data ingestion
- Technical indicator processing
- Machine learning price prediction (baseline model)
- AI-assisted trading decision engine (using Ollama)
- Risk-managed automated trade execution

Honest goal: positive risk-adjusted return (positive Sharpe ratio), NOT "high win rate".
The system must be backtested before any live execution.

---

## TECH STACK (100% Free / Open Source)

| Layer              | Tool                          |
|--------------------|-------------------------------|
| Language           | Python                        |
| Database           | PostgreSQL                    |
| Message Queue      | Redis                         |
| ML Libraries       | scikit-learn, XGBoost, pandas, numpy |
| AI Reasoning       | Ollama (local LLM)            |
| Containers         | Docker                        |
| Workflow           | n8n (scheduler)               |
| Dashboard          | Grafana or Streamlit          |

---

## SYSTEM ARCHITECTURE

```
Exchange APIs
↓
Data Collector (every 1 min)
↓
Redis Message Queue
↓
┌─────────────────┬──────────────────┐
Indicator Engine   Backtesting Module (NEW)
└─────────────────┴──────────────────┘
↓
PostgreSQL
├── market_data
├── indicators
├── predictions  ← needs: model_version, features_hash columns
├── trade_decisions
└── trades
↓
┌──────────────┬────────────────────┐
Baseline ML      Ollama LLM
(RF/XGBoost)     (structured prompt)
└──────────────┴────────────────────┘
↓
Decision Engine
(entry / stop_loss / take_profit / confidence)
↓
Risk Guard Module  ← MUST be a gate before any order
(1% risk/trade, max 3 open, 5% daily loss limit)
↓
Execution Engine
```

---

## FOLDER STRUCTURE

```
ai-trading-platform/
├── data_ingestion/       # Scripts to fetch market data from exchange APIs
├── data_processing/      # Technical indicator calculations
├── data_pipeline/        # Pipeline orchestration
├── ml_models/            # ML training, evaluation, versioning
├── decision_engine/      # Combines ML + Ollama output into decisions
├── execution_engine/
│   ├── risk_manager.py   # FIX: dedicated risk gate module
│   └── executor.py       # Order sending logic
├── backtesting/          # NEW: backtest module (added after assessment)
├── database/             # Schema, migrations
├── docker/               # Docker Compose config
├── notebooks/            # Experiments and EDA
└── docs/
    ├── ARCHITECTURE.md
    ├── ollama_prompt_template.md   # FIX: must be defined before building engine
    └── backtest_results/           # Store results here for portfolio evidence
```

---

## DATABASE SCHEMA

```sql
-- Raw market data
market_data (timestamp, symbol, open, high, low, close, volume)

-- Computed indicators (used as ML features)
indicators (timestamp, symbol, ema_20, ema_50, rsi_14, macd, atr, bb_upper, bb_lower, adx)

-- ML predictions (FIXED: added model_version and features_hash)
predictions (timestamp, symbol, prob_up, prob_down, model_version, features_hash)

-- AI decision output
trade_decisions (timestamp, symbol, entry_price, stop_loss, take_profit, confidence)

-- Executed trades and results
trades (timestamp, symbol, side, entry_price, exit_price, profit_loss)
```

---

## OLLAMA PROMPT TEMPLATE (must follow this format)

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

Enforced inside `execution_engine/risk_manager.py` before any order is sent:

- Max risk per trade: 1% of account
- Max open trades at once: 3
- Max daily loss: 5% of account
- No order bypasses risk_manager.py

---

## DEVELOPMENT ROADMAP

| Phase | Name                        | Status     |
|-------|-----------------------------|------------|
| 1     | Setup environment           | ⬜ Not started |
| 2     | Data collector              | ⬜ Not started |
| 3     | Database pipeline           | ⬜ Not started |
| 4     | Indicator engine            | ⬜ Not started |
| 5     | Machine learning (baseline) | ⬜ Not started |
| 5.5   | Backtesting & validation    | ⬜ Not started |
| 6     | AI decision engine (Ollama) | ⬜ Not started |
| 7     | Automated trading (live)    | ⬜ Not started |

**Rule**: Do NOT proceed to Phase 7 until backtesting shows positive Sharpe ratio
after accounting for transaction fees over at least 6 months of historical data.

---

## CURRENT CHECKPOINT

**Last completed:** Blueprint assessment and architecture review
**Currently working on:** Phase 1 — Environment setup
**Next task:** [ UPDATE THIS WHEN YOU CONTINUE ]

### Notes for next session:
- Blueprint has been reviewed and improved (see fixes above)
- Backtesting module added to roadmap as Phase 5.5
- risk_manager.py must be a hard gate (not optional)
- Ollama prompt must be specced in docs before building Phase 6
- Portfolio tip: document backtest results even if modest — shows engineering rigor

---

## HOW TO ASK CLAUDE FOR HELP

Paste one of these at the start of a new chat after uploading this file:

- "Help me set up Phase 1 — Docker, PostgreSQL, and Redis environment"
- "Help me build the data collector in Phase 2"
- "I finished Phase 3. Update my checkpoint and help me start Phase 4"
- "Review my risk_manager.py code"
- "Help me write the backtesting module"

---

*Last updated: Phase 0 — Blueprint finalized*
