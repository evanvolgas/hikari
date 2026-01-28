# Hikari Engineering Specification

> Implementable spec derived via Elenchus Socratic interrogation (3 rounds, 11 questions, 49 premises, 4 contradictions resolved, 100% area coverage).
>
> **Goal**: An LLM given this document produces all code, tests, configs, and migrations without asking clarifying questions.

---

## 1. What Hikari Is

Hikari is an open-source, OpenTelemetry-based LLM pipeline cost intelligence tool. It instruments multi-step LLM pipelines and provides end-to-end cost decomposition by stage.

**Hikari is a mirror, not an advisor.** It surfaces cost facts. It never judges output quality. It never recommends cheaper models.

## 2. Deliverables

Three components, one docker-compose, two migrations.

```
hikari/
  sdk/
    python/                    # Python SDK (hikari-python)
      pyproject.toml
      src/hikari/
        __init__.py            # Public API: configure(), set_pipeline_id(), set_stage()
        instrumentor.py        # Auto-patching orchestrator
        providers/
          __init__.py
          openai.py            # OpenAI monkey-patch
          anthropic.py         # Anthropic monkey-patch
          google.py            # Google monkey-patch
        pricing.py             # PricingModel class
        attributes.py          # hikari.* attribute constants
        exporter.py            # OTel SpanExporter -> collector
        context.py             # Context propagation helpers
      tests/
        conftest.py
        test_instrumentor.py
        test_pricing.py
        test_providers.py
    typescript/                # TypeScript SDK (hikari-js)
      package.json
      tsconfig.json
      vitest.config.ts
      src/
        index.ts               # Public API
        instrumentor.ts        # Auto-patching orchestrator
        providers/
          openai.ts
          anthropic.ts
          google.ts
        pricing.ts
        attributes.ts
        exporter.ts
        context.ts
      src/__tests__/
        instrumentor.test.ts
        pricing.test.ts
        providers.test.ts
  collector/                   # FastAPI collector + query API
    pyproject.toml
    src/collector/
      __init__.py
      app.py                   # FastAPI application
      ingest.py                # OTLP span ingestion
      storage.py               # Async PostgreSQL writer
      queries.py               # Pipeline cost query functions
      routes.py                # API route definitions
      models.py                # Pydantic request/response models
      config.py                # Settings (env-based)
    tests/
      test_ingest.py
      test_queries.py
      test_routes.py
      conftest.py
  migrations/
    001_initial_schema.sql
    002_continuous_aggregates.sql
  tests/
    integration/
      test_end_to_end.py       # SDK -> Collector -> Query roundtrip
  docker-compose.yml           # PostgreSQL + TimescaleDB + Collector
```

---

## 3. Span Attributes

All attributes are prefixed with `hikari.`. These are OTel span attributes, not separate telemetry.

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `hikari.pipeline_id` | string | No | Explicit pipeline grouping. Defaults to trace_id if absent. |
| `hikari.stage` | string | Yes | Pipeline stage. Auto-derived as `{provider}.{operation}`, user-overridable. |
| `hikari.model` | string | Yes | Model identifier (e.g., `gpt-4o`, `claude-3-haiku-20240307`). |
| `hikari.provider` | string | Yes | Provider name: `openai`, `anthropic`, `google`. |
| `hikari.tokens.input` | int | Yes* | Input token count from provider response. Null if unavailable. |
| `hikari.tokens.output` | int | Yes* | Output token count from provider response. Null if unavailable. |
| `hikari.cost.input` | float | No | Computed input cost in USD. Null if model not in pricing table. |
| `hikari.cost.output` | float | No | Computed output cost in USD. Null if model not in pricing table. |
| `hikari.cost.total` | float | No | `cost.input + cost.output`. Null if either component is null. |

*Yes = set whenever the provider response includes the data. Null when provider omits it.

**Null semantics**: Null means "unknown", never zero. Zero means the actual value is zero. This distinction drives the entire partial-coverage model.

---

## 4. Python SDK

### 4.1 Public API

```python
# src/hikari/__init__.py

def configure(
    *,
    pricing: dict[str, dict[str, float]] | None = None,
    collector_endpoint: str = "http://localhost:8000",
    batch_size: int = 100,
    flush_interval_seconds: float = 5.0,
    max_queue_size: int = 10_000,
) -> None:
    """Initialize Hikari instrumentation. Call once at application startup.

    Auto-detects and patches installed provider clients (OpenAI, Anthropic, Google).
    Providers not installed are silently skipped.
    Providers installed but with incompatible versions log a warning and are skipped.
    """

def set_pipeline_id(pipeline_id: str) -> None:
    """Set explicit pipeline ID on the current span context.
    Propagates to child spans via OTel context.
    If not called, pipeline_id defaults to the trace_id.
    """

def set_stage(stage: str) -> None:
    """Override the auto-derived stage name on the current span context.
    Default stage is '{provider}.{operation}' (e.g., 'openai.chat.completions.create').
    """

def shutdown() -> None:
    """Flush pending spans and restore original provider methods."""
```

### 4.2 Instrumentor

```python
# src/hikari/instrumentor.py

class HikariInstrumentor:
    """Orchestrates monkey-patching of provider clients."""

    def instrument(self) -> None:
        """Detect installed providers and patch them.

        For each provider:
        1. Try to import the provider module.
        2. If import fails -> skip (provider not installed).
        3. If import succeeds, check version meets minimum.
        4. If version too old -> log warning, skip.
        5. If version OK -> apply patch.
        """

    def uninstrument(self) -> None:
        """Restore all original methods."""
```

### 4.3 Provider Patches

Each provider patch wraps the target method to:
1. Start an OTel span named `{provider}.{operation}`.
2. Call the original method.
3. Extract token counts from the response.
4. Compute costs using the pricing model.
5. Set all `hikari.*` span attributes.
6. Return the original response unmodified.

**All of this happens in a try/except that swallows any Hikari-internal error. The user's call always succeeds, even if Hikari fails.**

#### OpenAI (Python)

```python
# src/hikari/providers/openai.py

# Target: openai.resources.chat.completions.Completions.create
#         openai.resources.chat.completions.AsyncCompletions.create
# Min version: openai >= 1.0
# Response token path: response.usage.prompt_tokens, response.usage.completion_tokens
# Model path: response.model (or request kwarg "model")
```

#### Anthropic (Python)

```python
# src/hikari/providers/anthropic.py

# Target: anthropic.resources.messages.Messages.create
#         anthropic.resources.messages.AsyncMessages.create
# Min version: anthropic >= 0.18
# Response token path: response.usage.input_tokens, response.usage.output_tokens
# Model path: response.model (or request kwarg "model")
```

#### Google (Python)

```python
# src/hikari/providers/google.py

# Target: google.generativeai.GenerativeModel.generate_content
# Min version: google-generativeai >= 0.3
# Response token path: response.usage_metadata.prompt_token_count,
#                      response.usage_metadata.candidates_token_count
# Model path: self.model_name on the GenerativeModel instance
```

### 4.4 Pricing Model

```python
# src/hikari/pricing.py

class PricingModel:
    """Loads and manages per-model token pricing."""

    def __init__(self, overrides: dict[str, dict[str, float]] | None = None) -> None:
        """Load pricing in order:
        1. overrides dict (if provided)
        2. HIKARI_PRICING_PATH env var -> JSON file
        3. Bundled default (src/hikari/default_pricing.json)

        Merge strategy: overrides win over env file wins over default.
        """

    def get(self, provider: str, model: str) -> tuple[float | None, float | None]:
        """Return (input_cost_per_token, output_cost_per_token) for the model.
        Returns (None, None) if model not in table.
        Lookup key: '{provider}/{model}' (e.g., 'openai/gpt-4o').
        """

    def compute_cost(
        self, provider: str, model: str, input_tokens: int | None, output_tokens: int | None
    ) -> tuple[float | None, float | None, float | None]:
        """Return (input_cost, output_cost, total_cost).
        Any component is None if tokens are None or model pricing is unknown.
        total_cost is None if either input_cost or output_cost is None.
        """

    def update(self, model_key: str, input_cost_per_token: float, output_cost_per_token: float) -> None:
        """Update pricing at runtime. model_key format: '{provider}/{model}'."""
```

**Default pricing JSON format** (`src/hikari/default_pricing.json`):
```json
{
  "openai/gpt-4o": {
    "input_cost_per_token": 0.0000025,
    "output_cost_per_token": 0.00001
  },
  "openai/gpt-4o-mini": {
    "input_cost_per_token": 0.00000015,
    "output_cost_per_token": 0.0000006
  },
  "anthropic/claude-3-5-sonnet-20241022": {
    "input_cost_per_token": 0.000003,
    "output_cost_per_token": 0.000015
  },
  "anthropic/claude-3-haiku-20240307": {
    "input_cost_per_token": 0.00000025,
    "output_cost_per_token": 0.00000125
  },
  "google/gemini-1.5-pro": {
    "input_cost_per_token": 0.00000125,
    "output_cost_per_token": 0.000005
  },
  "google/gemini-1.5-flash": {
    "input_cost_per_token": 0.000000075,
    "output_cost_per_token": 0.0000003
  }
}
```

### 4.5 Exporter

```python
# src/hikari/exporter.py

class HikariSpanExporter:
    """OTel SpanExporter that sends spans to the Hikari collector.

    - Batches spans (default 100 or 5s flush interval).
    - In-memory bounded queue (max 10,000 spans). Drops oldest on overflow.
    - HTTP POST to {collector_endpoint}/v1/traces with JSON body.
    - On failure: retry 3x with exponential backoff (1s, 2s, 4s).
    - After 3 failures: drop batch, log warning.
    - Never raises exceptions.
    """
```

### 4.6 Context Propagation

```python
# src/hikari/context.py

import contextvars

_pipeline_id: contextvars.ContextVar[str | None] = contextvars.ContextVar('hikari_pipeline_id', default=None)
_stage: contextvars.ContextVar[str | None] = contextvars.ContextVar('hikari_stage', default=None)

def get_pipeline_id() -> str | None: ...
def set_pipeline_id(pipeline_id: str) -> None: ...
def get_stage() -> str | None: ...
def set_stage(stage: str) -> None: ...
```

### 4.7 Attribute Constants

```python
# src/hikari/attributes.py

PIPELINE_ID = "hikari.pipeline_id"
STAGE = "hikari.stage"
MODEL = "hikari.model"
PROVIDER = "hikari.provider"
TOKENS_INPUT = "hikari.tokens.input"
TOKENS_OUTPUT = "hikari.tokens.output"
COST_INPUT = "hikari.cost.input"
COST_OUTPUT = "hikari.cost.output"
COST_TOTAL = "hikari.cost.total"
```

### 4.8 pyproject.toml

```toml
[project]
name = "hikari-sdk"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "opentelemetry-api>=1.20",
    "opentelemetry-sdk>=1.20",
    "httpx>=0.25",
]

[project.optional-dependencies]
openai = ["openai>=1.0"]
anthropic = ["anthropic>=0.18"]
google = ["google-generativeai>=0.3"]
all = ["hikari-sdk[openai,anthropic,google]"]
dev = [
    "pytest>=7.0",
    "pytest-asyncio>=0.21",
    "mypy>=1.5",
    "ruff>=0.1",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## 5. TypeScript SDK

Mirror of the Python SDK. Same behavior, TypeScript idioms.

### 5.1 Public API

```typescript
// src/index.ts

export interface HikariConfig {
  pricing?: Record<string, { inputCostPerToken: number; outputCostPerToken: number }>;
  collectorEndpoint?: string;  // default: "http://localhost:8000"
  batchSize?: number;          // default: 100
  flushIntervalMs?: number;    // default: 5000
  maxQueueSize?: number;       // default: 10_000
}

export function configure(config?: HikariConfig): void;
export function setPipelineId(pipelineId: string): void;
export function setStage(stage: string): void;
export function shutdown(): Promise<void>;
```

### 5.2 Provider Patches

```typescript
// src/providers/openai.ts
// Target: OpenAI.prototype.chat.completions.create (via prototype chain patching)
// Response token path: response.usage.prompt_tokens, response.usage.completion_tokens

// src/providers/anthropic.ts
// Target: Anthropic.prototype.messages.create
// Response token path: response.usage.input_tokens, response.usage.output_tokens

// src/providers/google.ts
// Target: GoogleGenerativeAI.prototype.getGenerativeModel (wrap returned model's generateContent)
// Response token path: response.usageMetadata.promptTokenCount, response.usageMetadata.candidatesTokenCount
```

### 5.3 Context Propagation

```typescript
// src/context.ts
import { AsyncLocalStorage } from "node:async_hooks";

interface HikariContext {
  pipelineId?: string;
  stage?: string;
}

const storage = new AsyncLocalStorage<HikariContext>();
```

### 5.4 package.json

```json
{
  "name": "hikari-js",
  "version": "0.1.0",
  "type": "module",
  "main": "dist/index.js",
  "types": "dist/index.d.ts",
  "engines": { "node": ">=20" },
  "scripts": {
    "build": "tsc",
    "test": "vitest run",
    "typecheck": "tsc --noEmit",
    "lint": "eslint src/"
  },
  "dependencies": {
    "@opentelemetry/api": "^1.7",
    "@opentelemetry/sdk-trace-base": "^1.20"
  },
  "devDependencies": {
    "typescript": "^5.3",
    "vitest": "^1.0",
    "eslint": "^8.50",
    "openai": "^4.0",
    "@anthropic-ai/sdk": "^0.18",
    "@google/generative-ai": "^0.3"
  }
}
```

### 5.5 tsconfig.json

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "Node16",
    "moduleResolution": "Node16",
    "lib": ["ES2022"],
    "outDir": "dist",
    "rootDir": "src",
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true
  },
  "include": ["src"],
  "exclude": ["node_modules", "dist", "src/__tests__"]
}
```

---

## 6. Collector + API

### 6.1 API Endpoints

#### `POST /v1/traces` -- Span Ingestion

Accepts OTLP JSON format (simplified: array of span objects with attributes).

**Request body:**
```json
{
  "resourceSpans": [
    {
      "scopeSpans": [
        {
          "spans": [
            {
              "traceId": "abc123",
              "spanId": "def456",
              "name": "openai.chat.completions.create",
              "startTimeUnixNano": "1706000000000000000",
              "endTimeUnixNano": "1706000001000000000",
              "attributes": [
                { "key": "hikari.pipeline_id", "value": { "stringValue": "pipe-1" } },
                { "key": "hikari.stage", "value": { "stringValue": "openai.chat.completions.create" } },
                { "key": "hikari.model", "value": { "stringValue": "gpt-4o" } },
                { "key": "hikari.provider", "value": { "stringValue": "openai" } },
                { "key": "hikari.tokens.input", "value": { "intValue": "150" } },
                { "key": "hikari.tokens.output", "value": { "intValue": "50" } },
                { "key": "hikari.cost.input", "value": { "doubleValue": 0.000375 } },
                { "key": "hikari.cost.output", "value": { "doubleValue": 0.0005 } },
                { "key": "hikari.cost.total", "value": { "doubleValue": 0.000875 } }
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

**Response (200):**
```json
{ "accepted": 1 }
```

**Response (207 partial):**
```json
{ "accepted": 3, "rejected": 1, "errors": ["span def789: missing required attribute hikari.stage"] }
```

#### `GET /v1/pipelines/{pipeline_id}/cost` -- Pipeline Cost Breakdown

**Response (200):**
```json
{
  "pipeline_id": "pipe-1",
  "total_cost": 0.0125,
  "is_partial": false,
  "coverage_ratio": 1.0,
  "stages": [
    {
      "stage": "openai.chat.completions.create",
      "model": "gpt-4o",
      "provider": "openai",
      "tokens_input": 1500,
      "tokens_output": 500,
      "cost_input": 0.00375,
      "cost_output": 0.005,
      "cost_total": 0.00875,
      "span_count": 1
    },
    {
      "stage": "anthropic.messages.create",
      "model": "claude-3-haiku-20240307",
      "provider": "anthropic",
      "tokens_input": 800,
      "tokens_output": 200,
      "cost_input": 0.0002,
      "cost_output": 0.00025,
      "cost_total": 0.00045,
      "span_count": 1
    }
  ],
  "first_seen": "2025-01-27T10:00:00Z",
  "last_seen": "2025-01-27T10:00:02Z"
}
```

**When partial (`is_partial: true`):**
```json
{
  "pipeline_id": "pipe-2",
  "total_cost": 0.008,
  "is_partial": true,
  "coverage_ratio": 0.67,
  "stages": [
    {
      "stage": "openai.chat.completions.create",
      "model": "gpt-4o",
      "provider": "openai",
      "tokens_input": 1000,
      "tokens_output": 300,
      "cost_input": 0.0025,
      "cost_output": 0.003,
      "cost_total": 0.0055,
      "span_count": 1
    },
    {
      "stage": "anthropic.messages.create",
      "model": "unknown-model",
      "provider": "anthropic",
      "tokens_input": 500,
      "tokens_output": 100,
      "cost_input": null,
      "cost_output": null,
      "cost_total": null,
      "span_count": 1
    }
  ],
  "first_seen": "2025-01-27T11:00:00Z",
  "last_seen": "2025-01-27T11:00:03Z"
}
```

`coverage_ratio` = (spans with non-null cost_total) / (total spans in pipeline).

#### `GET /v1/pipelines` -- List Pipelines

**Query params:** `start` (ISO8601), `end` (ISO8601), `limit` (int, default 100), `offset` (int, default 0).

**Response (200):**
```json
{
  "pipelines": [
    {
      "pipeline_id": "pipe-1",
      "total_cost": 0.0125,
      "is_partial": false,
      "span_count": 3,
      "first_seen": "2025-01-27T10:00:00Z",
      "last_seen": "2025-01-27T10:00:02Z"
    }
  ],
  "total": 1,
  "limit": 100,
  "offset": 0
}
```

#### `GET /v1/cost/trending` -- Cost Trending

**Query params:** `start` (ISO8601, required), `end` (ISO8601, required), `interval` (enum: `hour`, `day`, `week`), `group_by` (enum: `model`, `provider`, `stage`).

**Response (200):**
```json
{
  "buckets": [
    {
      "timestamp": "2025-01-27T10:00:00Z",
      "total_cost": 1.25,
      "request_count": 150,
      "avg_cost_per_request": 0.00833,
      "breakdown": [
        { "key": "gpt-4o", "cost": 0.90, "percentage": 72.0 },
        { "key": "claude-3-haiku-20240307", "cost": 0.35, "percentage": 28.0 }
      ]
    }
  ]
}
```

#### `GET /v1/health` -- Health Check

**Response (200):**
```json
{
  "status": "healthy",
  "db_connected": true,
  "buffer_usage": 0.02,
  "version": "0.1.0"
}
```

`buffer_usage` = current_buffer_size / max_buffer_size (50,000). `status` is `degraded` when `db_connected` is false; `unhealthy` when buffer_usage > 0.9.

### 6.2 Configuration

```python
# src/collector/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://hikari:hikari@localhost:5432/hikari"
    buffer_max_size: int = 50_000
    db_retry_interval_seconds: float = 10.0
    retention_days: int = 30
    host: str = "0.0.0.0"
    port: int = 8000

    model_config = {"env_prefix": "HIKARI_"}
```

### 6.3 Async Storage Writer

```python
# src/collector/storage.py

class SpanWriter:
    """Async PostgreSQL writer with resilience.

    - Receives spans from the ingestion endpoint.
    - Writes batches to the spans hypertable via asyncpg.
    - If DB unavailable: buffer in memory (max 50,000), retry every 10s.
    - If buffer full: drop oldest spans, log warning.
    - Exposes buffer_usage() -> float for health endpoint.
    """
```

### 6.4 Pydantic Models

```python
# src/collector/models.py
from pydantic import BaseModel
from datetime import datetime

class SpanAttribute(BaseModel):
    key: str
    value: dict  # {"stringValue": ...} | {"intValue": ...} | {"doubleValue": ...}

class Span(BaseModel):
    traceId: str
    spanId: str
    name: str
    startTimeUnixNano: str
    endTimeUnixNano: str
    attributes: list[SpanAttribute]

class ScopeSpans(BaseModel):
    spans: list[Span]

class ResourceSpans(BaseModel):
    scopeSpans: list[ScopeSpans]

class IngestRequest(BaseModel):
    resourceSpans: list[ResourceSpans]

class IngestResponse(BaseModel):
    accepted: int
    rejected: int = 0
    errors: list[str] = []

class StageCost(BaseModel):
    stage: str
    model: str
    provider: str
    tokens_input: int | None
    tokens_output: int | None
    cost_input: float | None
    cost_output: float | None
    cost_total: float | None
    span_count: int

class PipelineCostResponse(BaseModel):
    pipeline_id: str
    total_cost: float
    is_partial: bool
    coverage_ratio: float
    stages: list[StageCost]
    first_seen: datetime
    last_seen: datetime

class PipelineSummary(BaseModel):
    pipeline_id: str
    total_cost: float
    is_partial: bool
    span_count: int
    first_seen: datetime
    last_seen: datetime

class PipelineListResponse(BaseModel):
    pipelines: list[PipelineSummary]
    total: int
    limit: int
    offset: int

class TrendingBucketBreakdown(BaseModel):
    key: str
    cost: float
    percentage: float

class TrendingBucket(BaseModel):
    timestamp: datetime
    total_cost: float
    request_count: int
    avg_cost_per_request: float
    breakdown: list[TrendingBucketBreakdown]

class TrendingResponse(BaseModel):
    buckets: list[TrendingBucket]

class HealthResponse(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    db_connected: bool
    buffer_usage: float
    version: str
```

---

## 7. Database Schema

### 7.1 Migration 001: Initial Schema

```sql
-- migrations/001_initial_schema.sql

CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE spans (
    time            TIMESTAMPTZ     NOT NULL,
    trace_id        TEXT            NOT NULL,
    span_id         TEXT            NOT NULL,
    span_name       TEXT            NOT NULL,
    pipeline_id     TEXT            NOT NULL,  -- defaults to trace_id if not set
    stage           TEXT            NOT NULL,
    model           TEXT            NOT NULL,
    provider        TEXT            NOT NULL,
    tokens_input    INTEGER,                   -- null if unavailable
    tokens_output   INTEGER,                   -- null if unavailable
    cost_input      DOUBLE PRECISION,          -- null if unknown pricing
    cost_output     DOUBLE PRECISION,          -- null if unknown pricing
    cost_total      DOUBLE PRECISION,          -- null if either component null
    duration_ms     DOUBLE PRECISION NOT NULL,

    PRIMARY KEY (time, span_id)
);

-- Convert to hypertable, 1-day chunks
SELECT create_hypertable('spans', 'time', chunk_time_interval => INTERVAL '1 day');

-- Indexes for query patterns
CREATE INDEX idx_spans_pipeline_id ON spans (pipeline_id, time DESC);
CREATE INDEX idx_spans_trace_id ON spans (trace_id, time DESC);
CREATE INDEX idx_spans_model ON spans (model, time DESC);
CREATE INDEX idx_spans_provider ON spans (provider, time DESC);

-- Retention policy (default 30 days, configurable via HIKARI_RETENTION_DAYS at application level)
SELECT add_retention_policy('spans', INTERVAL '30 days');
```

### 7.2 Migration 002: Continuous Aggregates

```sql
-- migrations/002_continuous_aggregates.sql

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
```

---

## 8. Docker Compose

```yaml
# docker-compose.yml
services:
  db:
    image: timescale/timescaledb:latest-pg16
    environment:
      POSTGRES_USER: hikari
      POSTGRES_PASSWORD: hikari
      POSTGRES_DB: hikari
    ports:
      - "5432:5432"
    volumes:
      - hikari_data:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d

  collector:
    build: ./collector
    environment:
      HIKARI_DATABASE_URL: "postgresql+asyncpg://hikari:hikari@db:5432/hikari"
      HIKARI_HOST: "0.0.0.0"
      HIKARI_PORT: "8000"
    ports:
      - "8000:8000"
    depends_on:
      - db

volumes:
  hikari_data:
```

---

## 9. Error Handling

### SDK-Side (Python + TypeScript)

1. **All Hikari code runs inside try/except (Python) or try/catch (TypeScript).** If any Hikari-internal error occurs during instrumentation, the original provider call proceeds as if Hikari were not installed.
2. Spans queued to bounded in-memory queue (10,000 max). Oldest dropped on overflow.
3. Exporter sends batches with 5s timeout. On failure: 3 retries with exponential backoff (1s, 2s, 4s). After 3 failures: drop batch, log warning.
4. SDK never raises/throws to user code.

### Collector-Side

1. Ingestion endpoint validates spans, enqueues to async write buffer.
2. If PostgreSQL unavailable: buffer in memory (50,000 max), retry writes every 10s.
3. If buffer overflows: drop oldest, log warning.
4. Health endpoint: `degraded` when DB unreachable, `unhealthy` when buffer > 90% full.

---

## 10. Graceful Degradation

Three failure modes, all handled without breaking anything:

| Scenario | What Happens | Pipeline Effect |
|----------|-------------|-----------------|
| Provider not patchable (wrong version, missing method) | Skip patching, log warning. Provider calls unaffected. | Fewer spans in pipeline. |
| Model not in pricing table | Span has token counts but null costs. | `is_partial: true`, `coverage_ratio < 1.0`. |
| Mixed pipeline (some spans costed, some not) | Sum known costs. | `total_cost` = sum of knowns. Reported as "at least $X". |

`coverage_ratio` = count(spans where cost_total IS NOT NULL) / count(all spans in pipeline).

---

## 11. Performance Constraints

| Metric | Target |
|--------|--------|
| SDK wrapper overhead per call | < 5ms |
| SDK batch flush | 100 spans or 5 seconds |
| Collector ingestion p99 (batch up to 1000) | < 100ms |
| Pipeline lookup by trace_id | < 50ms |
| Trending query (7 days, aggregated) | < 500ms |
| Raw storage per day (1M requests, ~3M spans) | ~1.5 GB |
| Steady-state storage (30-day retention) | ~45 GB |

---

## 12. Test Expectations

### Python SDK Tests

**test_instrumentor.py:**
- `test_instrument_patches_openai` -- after `instrument()`, the OpenAI method is wrapped; calling it produces a span with `hikari.*` attributes.
- `test_instrument_skips_missing_provider` -- if openai is not importable, `instrument()` does not raise and logs a skip message.
- `test_uninstrument_restores_originals` -- after `uninstrument()`, the original methods are back.
- `test_instrument_logs_warning_for_old_version` -- with a version below minimum, logs a warning and skips.

**test_pricing.py:**
- `test_default_pricing_loads` -- `PricingModel()` loads bundled defaults.
- `test_unknown_model_returns_none` -- `get("openai", "nonexistent")` returns `(None, None)`.
- `test_compute_cost_with_known_model` -- correct multiplication.
- `test_compute_cost_with_null_tokens` -- returns `(None, None, None)`.
- `test_update_pricing` -- after `update()`, new pricing is used.
- `test_env_var_override` -- with `HIKARI_PRICING_PATH` set, loads from that file.

**test_providers.py:**
- For each provider: mock the provider client, call the patched method, assert span has correct `hikari.*` attributes and correct token counts extracted from mock response.
- `test_provider_error_does_not_propagate` -- if Hikari internals raise, the original response is still returned.

### TypeScript SDK Tests

Equivalent to Python tests, using vitest and mocked provider clients.

### Collector Tests

**test_ingest.py:**
- `test_ingest_valid_spans` -- POST valid OTLP JSON, get 200 with `accepted: N`.
- `test_ingest_invalid_span_rejected` -- POST span missing required attributes, get 207 with errors.

**test_queries.py:**
- `test_pipeline_cost_full_coverage` -- insert spans with costs, query returns `is_partial: false`, correct totals.
- `test_pipeline_cost_partial` -- insert mix of costed and null-cost spans, returns `is_partial: true` with correct `coverage_ratio`.
- `test_pipeline_list` -- insert multiple pipelines, list returns them with pagination.
- `test_trending` -- insert spans across time buckets, trending returns correct aggregations.

**test_routes.py:**
- `test_health_healthy` -- with DB connected, returns `healthy`.
- `test_health_degraded` -- with DB disconnected, returns `degraded`.

### Integration Tests

**test_end_to_end.py:**
- Requires docker-compose running (PostgreSQL + TimescaleDB + Collector).
- Python SDK `configure()` -> mock an OpenAI call -> SDK sends span to collector -> query `/v1/pipelines/{id}/cost` -> verify cost breakdown matches expectations.

---

## 13. Out of Scope for V1

- Output quality evaluation
- Model routing or recommendations
- Streaming ingestion (Kafka/NATS)
- Horizontal scaling
- Web UI
- Authentication/authorization (self-hosted, internal network)
- CORS

---

## 14. Elenchus Session Metadata

- **Epic ID**: epic-mkxhlp6v-93UpZX3A9wEv
- **Session ID**: session-mkxhlp6v-uwghdyXHRQhQ
- **Spec ID**: spec-mkxhqij4-9zSquvyJTc0o
- **Rounds**: 3
- **Questions answered**: 11
- **Premises extracted**: 49
- **Contradictions detected**: 4 (all resolved)
- **Coverage**: scope, success, constraint, risk, technical (100%)
- **Average answer quality**: 5.0/5
