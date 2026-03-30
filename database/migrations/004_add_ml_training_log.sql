-- Tracking training history untuk monitoring performa
CREATE TABLE IF NOT EXISTS ml_training_log (
    id              BIGSERIAL PRIMARY KEY,
    symbol          VARCHAR(20) NOT NULL,
    model_type      VARCHAR(10) NOT NULL,
    version         VARCHAR(50) NOT NULL,
    train_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    train_rows      INTEGER NOT NULL,
    label_balance   NUMERIC(5,4),
    positive_labels INTEGER,
    roc_auc         NUMERIC(6,4),
    f1_score        NUMERIC(6,4),
    trades_used     INTEGER,
    trigger_reason  VARCHAR(20),  -- 'scheduled', 'performance_drop', 'manual'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_ml_training_log_symbol ON ml_training_log(symbol);
CREATE INDEX idx_ml_training_log_version ON ml_training_log(version);