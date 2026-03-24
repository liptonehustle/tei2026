-- database/migrations/002_trade_decisions.sql
-- Run this if trade_decisions table doesn't have all required columns yet.
-- Safe to run multiple times (uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS trade_decisions (
    id              SERIAL PRIMARY KEY,
    symbol          VARCHAR(20)     NOT NULL,
    timeframe       VARCHAR(10)     NOT NULL DEFAULT '5m',
    action          VARCHAR(10)     NOT NULL CHECK (action IN ('buy', 'sell', 'hold')),
    entry_price     NUMERIC(20, 8),
    stop_loss       NUMERIC(20, 8),
    take_profit     NUMERIC(20, 8),
    ml_prob_up      NUMERIC(8, 6),
    ml_prob_down    NUMERIC(8, 6),
    ollama_confidence NUMERIC(5, 4),
    ollama_reasoning  TEXT,
    raw_response    JSONB,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Add missing columns if table already exists
ALTER TABLE trade_decisions ADD COLUMN IF NOT EXISTS timeframe       VARCHAR(10) DEFAULT '5m';
ALTER TABLE trade_decisions ADD COLUMN IF NOT EXISTS ml_prob_up      NUMERIC(8, 6);
ALTER TABLE trade_decisions ADD COLUMN IF NOT EXISTS ml_prob_down    NUMERIC(8, 6);
ALTER TABLE trade_decisions ADD COLUMN IF NOT EXISTS ollama_confidence NUMERIC(5, 4);
ALTER TABLE trade_decisions ADD COLUMN IF NOT EXISTS ollama_reasoning  TEXT;
ALTER TABLE trade_decisions ADD COLUMN IF NOT EXISTS raw_response    JSONB;

-- Index for fast lookup by symbol + time
CREATE INDEX IF NOT EXISTS idx_trade_decisions_symbol_time
    ON trade_decisions (symbol, created_at DESC);

-- Verify
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'trade_decisions'
ORDER BY ordinal_position;
