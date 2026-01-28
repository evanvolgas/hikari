# Hikari Specification

> Generated via Elenchus Socratic interrogation. 9 questions, 4 contradictions resolved, 33 premises extracted.

## Problem Statement

Existing LLM observability tools (Langfuse, Helicone, Arize Phoenix, Logfire) track per-call token counts and costs. None answer the question that matters for teams running multi-step pipelines: **what did this user request cost end-to-end, broken down by stage, and how is that trending?**

Hikari is an open-source, OpenTelemetry-based LLM pipeline cost intelligence tool. It instruments LLM pipelines and provides:

1. **End-to-end pipeline cost decomposition** -- the full cost of a user request across multiple LLM calls, retrieval steps, rerankers, and tool invocations, broken down by stage.
2. **Cost context for human judgment** -- per-stage breakdown showing model used, token counts, and cost percentage. Humans identify optimization opportunities; Hikari does not judge quality or recommend cheaper models.
3. **Cost trending and drift detection** -- how per-request cost changes over time, with alerting when costs shift significantly.

## Scope

### In Scope

- SDK instrumentation for Python and TypeScript LLM provider clients
- Auto-instrumentation via monkey-patching (OpenAI, Anthropic, Google, etc.)
- Custom OTel span attributes for cost annotation (pipeline ID, stage metadata, model, tokens, cost)
- Pipeline-level cost aggregation by trace ID (default) or explicit pipeline ID (override)
- Graceful degradation with partial instrumentation (unknown cost gaps clearly marked)
- Async span ingestion and storage in PostgreSQL + TimescaleDB
- Configurable data retention (raw spans 7-30 days, rollups indefinitely)
- Pluggable, user-updatable pricing model
- Raw token counts surfaced alongside computed costs for verifiability
- Self-hostable deployment

### Out of Scope

- Output quality evaluation (Arbiter's domain)
- Model routing or recommendations (Conduit's domain)
- Waste labeling or anomaly classification
- Streaming ingestion (Kafka/NATS) at v1
- Horizontal scaling at v1
- Web UI at v1 (API and query interface first)

## Core Abstraction: Pipeline

A **pipeline** is the unit of cost accounting.

- **Default**: A pipeline equals an OpenTelemetry trace. All spans sharing a `trace_id` belong to one pipeline.
- **Override**: Users can set a `hikari.pipeline_id` span attribute to define custom pipeline boundaries. This supports cases where one trace contains multiple logical pipelines, or a pipeline spans multiple traces.

## Architecture

### Instrumentation Layer (SDK)

- OTel-native: uses OpenTelemetry for trace/span propagation. No proxy. No latency penalty.
- Hikari enriches spans with custom attributes:
  - `hikari.pipeline_id` -- explicit pipeline grouping (optional)
  - `hikari.stage` -- pipeline stage name
  - `hikari.model` -- model identifier (e.g., `gpt-4`, `claude-3-haiku`)
  - `hikari.tokens.input` -- input token count
  - `hikari.tokens.output` -- output token count
  - `hikari.cost.input` -- computed input cost (USD)
  - `hikari.cost.output` -- computed output cost (USD)
  - `hikari.cost.total` -- computed total cost (USD)
  - `hikari.provider` -- provider name (openai, anthropic, google, etc.)
- Auto-instrumentation via monkey-patching of provider client libraries
- SDKs: Python and TypeScript at v1

### Ingestion Layer

- Async span processing (no blocking on the hot path)
- OTLP-compatible collector endpoint
- Batch writes to storage

### Storage Layer

- PostgreSQL with TimescaleDB extension
- Hypertables for span data (time-partitioned)
- Continuous aggregation for cost rollups (hourly, daily, weekly)
- Configurable retention policies:
  - Raw spans: 7-30 days (user-configurable)
  - Aggregated rollups: indefinite

### Cost Computation

- Pipeline cost = sum of `hikari.cost.total` across all spans sharing a trace ID (or `hikari.pipeline_id`)
- Per-stage cost = sum grouped by `hikari.stage`
- Per-model cost = sum grouped by `hikari.model`
- Pricing model is pluggable: ships with default provider pricing, users can override
- Raw token counts always available alongside computed costs for independent verification

### Partial Coverage

- Hikari provides value from the first instrumented span
- Uninstrumented steps appear as gaps in the pipeline view
- Pipeline cost is reported as "at least $X" when gaps exist, with clear indication of missing stages

## Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Wire protocol | OpenTelemetry | Industry standard, no vendor lock-in, existing ecosystem |
| Cost enrichment | Custom span attributes | Richer than pure OTel, stays standards-compliant |
| Pipeline boundary | Trace ID default + explicit override | Simple default, flexible escape hatch |
| Instrumentation | Monkey-patching provider SDKs | Minimal user friction, proven pattern (OpenLLMetry) |
| Storage | PostgreSQL + TimescaleDB | Familiar ops story, native time-series optimization |
| Quality judgment | None | Avoids scope overlap with Arbiter; Hikari is a mirror, not an advisor |
| Language SDKs | Python + TypeScript v1 | Covers majority of LLM pipeline and agent framework ecosystems |

## Constraints

- V1 targets 100K-1M requests per day
- No streaming ingestion (Kafka/NATS) required at v1
- No horizontal scaling required at v1
- Async processing for span ingestion (never block the user's hot path)

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Instrumentation fatigue -- wrapping clients is too much friction | Medium | High | Auto-instrumentation via monkey-patching. One import, zero code changes. |
| Cost data accuracy -- provider pricing changes, token counts wrong | Medium | High | Pluggable pricing model users can update. Raw token counts always shown for verification. |
| Storage bloat -- 1M req/day with multiple spans per request | Medium | Medium | TimescaleDB retention policies + continuous aggregation. Raw spans 7-30 days, rollups indefinite. |

## Success Criteria

Hikari succeeds when Ashita AI has a credible, well-engineered observability tool that rounds out its portfolio. Engineering quality matters more than viral adoption. The tool must be genuinely useful to teams running LLM pipelines in production, not a portfolio placeholder.

## Relationship to Ashita Portfolio

Hikari is fully independent -- no dependency on other Ashita tools. It complements:

- **Arbiter** (evaluation): Hikari shows cost; Arbiter judges quality. Together they answer "was the spend justified?"
- **Conduit** (routing): Hikari shows which models are used where and at what cost; Conduit decides which model to use.
- **Engram** (memory): Independent concerns.
- **Tessera** (data contracts): Both enforce "contracts" -- Tessera on data schemas, Hikari could potentially enforce cost budgets per pipeline (future).

## Elenchus Session Metadata

- **Epic ID**: epic-mkxgwa3r-A4HvehIIwOJ5
- **Session ID**: session-mkxgwa3r-T5i2n8_KhRvm
- **Spec ID**: spec-mkxh5a1p-Z8eaLjShS3QP
- **Rounds**: 4
- **Questions answered**: 9
- **Premises extracted**: 33
- **Contradictions detected**: 4 (all resolved)
- **Coverage**: scope, success, constraint, risk, technical (100%)
- **Average answer quality**: 4.67/5
