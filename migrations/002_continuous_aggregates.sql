-- Hourly aggregate
CREATE MATERIALIZED VIEW cost_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 hour', time) AS bucket,
    pipeline_id,
    stage,
    model,
    provider,
    SUM(cost_total)     AS total_cost,
    SUM(tokens_input)   AS total_tokens_input,
    SUM(tokens_output)  AS total_tokens_output,
    COUNT(*)            AS span_count,
    AVG(cost_total)     AS avg_cost_per_span
FROM spans
WHERE cost_total IS NOT NULL
GROUP BY bucket, pipeline_id, stage, model, provider
WITH NO DATA;

SELECT add_continuous_aggregate_policy('cost_hourly',
    start_offset    => INTERVAL '2 hours',
    end_offset      => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes'
);

-- Daily aggregate
CREATE MATERIALIZED VIEW cost_daily
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 day', time) AS bucket,
    pipeline_id,
    stage,
    model,
    provider,
    SUM(cost_total)     AS total_cost,
    SUM(tokens_input)   AS total_tokens_input,
    SUM(tokens_output)  AS total_tokens_output,
    COUNT(*)            AS span_count,
    AVG(cost_total)     AS avg_cost_per_span
FROM spans
WHERE cost_total IS NOT NULL
GROUP BY bucket, pipeline_id, stage, model, provider
WITH NO DATA;

SELECT add_continuous_aggregate_policy('cost_daily',
    start_offset    => INTERVAL '2 days',
    end_offset      => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour'
);

-- Weekly aggregate
CREATE MATERIALIZED VIEW cost_weekly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket('1 week', time) AS bucket,
    pipeline_id,
    stage,
    model,
    provider,
    SUM(cost_total)     AS total_cost,
    SUM(tokens_input)   AS total_tokens_input,
    SUM(tokens_output)  AS total_tokens_output,
    COUNT(*)            AS span_count,
    AVG(cost_total)     AS avg_cost_per_span
FROM spans
WHERE cost_total IS NOT NULL
GROUP BY bucket, pipeline_id, stage, model, provider
WITH NO DATA;

SELECT add_continuous_aggregate_policy('cost_weekly',
    start_offset    => INTERVAL '2 weeks',
    end_offset      => INTERVAL '6 hours',
    schedule_interval => INTERVAL '6 hours'
);
