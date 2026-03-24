-- =============================================================
-- AI Trading Platform — Database Schema
-- Migration: 003_strategies.sql
-- Adds strategy signal tracking and virtual P&L per strategy
-- =============================================================

-- -------------------------------------------------------------
-- strategy_signals
-- Raw signal output from each strategy every cycle.
-- Even if not executed, signal is recorded for analysis.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strategy_signals (
    id              BIGSERIAL       PRIMARY KEY,
    timestamp       TIMESTAMPTZ     NOT NULL,
    strategy_name   VARCHAR(50)     NOT NULL,   -- e.g. 'rsi_mean_reversion'
    symbol          VARCHAR(20)     NOT NULL,
    timeframe       VARCHAR(5)      NOT NULL DEFAULT '5m',
    action          VARCHAR(10)     NOT NULL CHECK (action IN ('buy', 'sell', 'hold')),
    confidence      NUMERIC(5, 4)   NOT NULL,   -- 0.0000 to 1.0000
    entry_price     NUMERIC(20, 8),
    stop_loss       NUMERIC(20, 8),
    take_profit     NUMERIC(20, 8),
    reasoning       TEXT,
    was_selected    BOOLEAN         NOT NULL DEFAULT FALSE,  -- was this the strongest signal?
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_strategy_time
    ON strategy_signals (strategy_name, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_symbol_time
    ON strategy_signals (symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_strategy_signals_selected
    ON strategy_signals (was_selected, timestamp DESC);

-- -------------------------------------------------------------
-- strategy_virtual_trades
-- Virtual P&L per strategy — tracks what would have happened
-- if each strategy's signal was executed independently.
-- This is separate from real trades table.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strategy_virtual_trades (
    id                  BIGSERIAL       PRIMARY KEY,
    strategy_name       VARCHAR(50)     NOT NULL,
    symbol              VARCHAR(20)     NOT NULL,
    side                VARCHAR(5)      NOT NULL CHECK (side IN ('buy', 'sell')),
    entry_price         NUMERIC(20, 8)  NOT NULL,
    exit_price          NUMERIC(20, 8),
    quantity            NUMERIC(20, 8)  NOT NULL,
    virtual_pnl         NUMERIC(20, 8),
    virtual_pnl_pct     NUMERIC(10, 4),
    status              VARCHAR(10)     NOT NULL CHECK (status IN ('open', 'closed')),
    exit_reason         VARCHAR(20),    -- 'stop_loss', 'take_profit', 'timeout'
    stop_loss           NUMERIC(20, 8),
    take_profit         NUMERIC(20, 8),
    signal_id           BIGINT          REFERENCES strategy_signals(id),
    entry_time          TIMESTAMPTZ     NOT NULL,
    exit_time           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_svt_strategy_time
    ON strategy_virtual_trades (strategy_name, entry_time DESC);

CREATE INDEX IF NOT EXISTS idx_svt_symbol_time
    ON strategy_virtual_trades (symbol, entry_time DESC);

CREATE INDEX IF NOT EXISTS idx_svt_status
    ON strategy_virtual_trades (status);

-- -------------------------------------------------------------
-- strategy_performance_summary
-- Aggregated stats per strategy — updated after each close.
-- Used by Grafana for strategy comparison dashboard.
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS strategy_performance_summary (
    id                  BIGSERIAL       PRIMARY KEY,
    strategy_name       VARCHAR(50)     NOT NULL UNIQUE,
    total_signals       INTEGER         NOT NULL DEFAULT 0,
    total_trades        INTEGER         NOT NULL DEFAULT 0,
    winning_trades      INTEGER         NOT NULL DEFAULT 0,
    losing_trades       INTEGER         NOT NULL DEFAULT 0,
    win_rate            NUMERIC(5, 4)   NOT NULL DEFAULT 0,
    total_virtual_pnl   NUMERIC(20, 8)  NOT NULL DEFAULT 0,
    avg_pnl_per_trade   NUMERIC(20, 8)  NOT NULL DEFAULT 0,
    avg_confidence      NUMERIC(5, 4)   NOT NULL DEFAULT 0,
    best_trade_pnl      NUMERIC(20, 8)  NOT NULL DEFAULT 0,
    worst_trade_pnl     NUMERIC(20, 8)  NOT NULL DEFAULT 0,
    times_selected      INTEGER         NOT NULL DEFAULT 0,  -- how often was this the strongest signal
    last_updated        TIMESTAMPTZ     DEFAULT NOW()
);

-- Pre-insert rows for all 5 strategies
INSERT INTO strategy_performance_summary (strategy_name)
VALUES
    ('rsi_mean_reversion'),
    ('bb_squeeze_breakout'),
    ('ema_crossover_volume'),
    ('macd_divergence'),
    ('multi_confluence')
ON CONFLICT (strategy_name) DO NOTHING;

-- -------------------------------------------------------------
-- Confirmation
-- -------------------------------------------------------------
DO $$
BEGIN
    RAISE NOTICE 'Strategy tables created successfully.';
END $$;
