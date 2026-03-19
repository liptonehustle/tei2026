-- =============================================================
-- AI Trading Platform — Database Schema
-- Migration: 001_init.sql
-- Runs automatically on first PostgreSQL container start
-- =============================================================

-- Enable TimescaleDB extension if available (optional but ideal for time-series)
-- CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- -------------------------------------------------------------
-- market_data
-- Raw OHLCV candles from exchange APIs
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS market_data (
    id          BIGSERIAL,
    timestamp   TIMESTAMPTZ     NOT NULL,
    symbol      VARCHAR(20)     NOT NULL,   -- e.g. 'BTC/USDT'
    timeframe   VARCHAR(5)      NOT NULL,   -- e.g. '1m', '5m', '1h'
    open        NUMERIC(20, 8)  NOT NULL,
    high        NUMERIC(20, 8)  NOT NULL,
    low         NUMERIC(20, 8)  NOT NULL,
    close       NUMERIC(20, 8)  NOT NULL,
    volume      NUMERIC(30, 8)  NOT NULL,
    source      VARCHAR(50)     NOT NULL,   -- e.g. 'binance', 'yahoo'
    created_at  TIMESTAMPTZ     DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_market_data_unique
    ON market_data (timestamp, symbol, timeframe, source);

CREATE INDEX IF NOT EXISTS idx_market_data_symbol_time
    ON market_data (symbol, timestamp DESC);

-- -------------------------------------------------------------
-- indicators
-- Computed technical indicators (used as ML features)
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS indicators (
    id          BIGSERIAL,
    timestamp   TIMESTAMPTZ     NOT NULL,
    symbol      VARCHAR(20)     NOT NULL,
    timeframe   VARCHAR(5)      NOT NULL,
    ema_20      NUMERIC(20, 8),
    ema_50      NUMERIC(20, 8),
    rsi_14      NUMERIC(10, 4),
    macd        NUMERIC(20, 8),
    macd_signal NUMERIC(20, 8),
    macd_hist   NUMERIC(20, 8),
    atr         NUMERIC(20, 8),
    bb_upper    NUMERIC(20, 8),
    bb_middle   NUMERIC(20, 8),
    bb_lower    NUMERIC(20, 8),
    adx         NUMERIC(10, 4),
    created_at  TIMESTAMPTZ     DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_indicators_unique
    ON indicators (timestamp, symbol, timeframe);

CREATE INDEX IF NOT EXISTS idx_indicators_symbol_time
    ON indicators (symbol, timestamp DESC);

-- -------------------------------------------------------------
-- predictions
-- ML model output — includes model versioning for comparison
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS predictions (
    id              BIGSERIAL       PRIMARY KEY,
    timestamp       TIMESTAMPTZ     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    timeframe       VARCHAR(5)      NOT NULL,
    prob_up         NUMERIC(6, 4)   NOT NULL,   -- 0.0000 to 1.0000
    prob_down       NUMERIC(6, 4)   NOT NULL,
    prob_sideways   NUMERIC(6, 4),
    model_version   VARCHAR(50)     NOT NULL,   -- e.g. 'xgb_v1.2', 'rf_v2.0'
    features_hash   VARCHAR(64),                -- SHA256 of feature vector (for reproducibility)
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_predictions_symbol_time
    ON predictions (symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_predictions_model_version
    ON predictions (model_version);

-- -------------------------------------------------------------
-- trade_decisions
-- Output from the AI decision engine
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade_decisions (
    id              BIGSERIAL       PRIMARY KEY,
    timestamp       TIMESTAMPTZ     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    action          VARCHAR(10)     NOT NULL    CHECK (action IN ('buy', 'sell', 'hold')),
    entry_price     NUMERIC(20, 8),
    stop_loss       NUMERIC(20, 8),
    take_profit     NUMERIC(20, 8),
    confidence      NUMERIC(5, 4),              -- 0.0000 to 1.0000
    reasoning       TEXT,
    prediction_id   BIGINT          REFERENCES predictions(id),
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trade_decisions_symbol_time
    ON trade_decisions (symbol, timestamp DESC);

-- -------------------------------------------------------------
-- trades
-- Executed trades and their final P&L
-- -------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    id              BIGSERIAL       PRIMARY KEY,
    timestamp       TIMESTAMPTZ     NOT NULL,   -- entry time
    closed_at       TIMESTAMPTZ,                -- exit time
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(5)      NOT NULL    CHECK (side IN ('buy', 'sell')),
    entry_price     NUMERIC(20, 8)  NOT NULL,
    exit_price      NUMERIC(20, 8),
    quantity        NUMERIC(20, 8)  NOT NULL,
    profit_loss     NUMERIC(20, 8),
    profit_loss_pct NUMERIC(10, 4),
    status          VARCHAR(10)     NOT NULL    CHECK (status IN ('open', 'closed', 'cancelled')),
    decision_id     BIGINT          REFERENCES trade_decisions(id),
    notes           TEXT,
    created_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
    ON trades (symbol, timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_trades_status
    ON trades (status);

-- -------------------------------------------------------------
-- Confirmation message
-- -------------------------------------------------------------
DO $$
BEGIN
    RAISE NOTICE 'Trading platform schema created successfully.';
END $$;
