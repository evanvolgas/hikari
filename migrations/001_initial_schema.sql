CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE spans (
    time            TIMESTAMPTZ     NOT NULL,
    trace_id        TEXT            NOT NULL,
    span_id         TEXT            NOT NULL,
    span_name       TEXT            NOT NULL,
    pipeline_id     TEXT            NOT NULL,
    stage           TEXT            NOT NULL,
    model           TEXT            NOT NULL,
    provider        TEXT            NOT NULL,
    tokens_input    INTEGER,
    tokens_output   INTEGER,
    cost_input      DOUBLE PRECISION,
    cost_output     DOUBLE PRECISION,
    cost_total      DOUBLE PRECISION,
    duration_ms     DOUBLE PRECISION NOT NULL,

    PRIMARY KEY (time, span_id)
);

SELECT create_hypertable('spans', 'time', chunk_time_interval => INTERVAL '1 day');

CREATE INDEX idx_spans_pipeline_id ON spans (pipeline_id, time DESC);
CREATE INDEX idx_spans_trace_id ON spans (trace_id, time DESC);
CREATE INDEX idx_spans_model ON spans (model, time DESC);
CREATE INDEX idx_spans_provider ON spans (provider, time DESC);

SELECT add_retention_policy('spans', INTERVAL '30 days');
