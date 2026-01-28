# Hikari

Open-source, OpenTelemetry-based LLM pipeline cost intelligence.

Named after the Japanese word for "light" (光).

## What It Does

Hikari instruments multi-step LLM pipelines and provides end-to-end cost decomposition by stage. Unlike general-purpose observability tools, Hikari is purpose-built for the specific challenge of tracking costs across complex LLM workflows where a single user request might trigger multiple models across multiple providers.

**Key insight**: In production LLM applications, a single pipeline might use GPT-4 for reasoning, Claude for code generation, and Gemini for summarization. Hikari tells you exactly what each stage costs.

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐
│   Your Application  │     │   Your Application  │
│   (Python SDK)      │     │   (TypeScript SDK)  │
└─────────┬───────────┘     └─────────┬───────────┘
          │                           │
          │  OTLP spans with          │
          │  hikari.* attributes      │
          ▼                           ▼
     ┌────────────────────────────────────┐
     │           Hikari Collector         │
     │  POST /v1/traces (OTLP-compatible) │
     └─────────────────┬──────────────────┘
                       │
                       ▼
     ┌────────────────────────────────────┐
     │   PostgreSQL + TimescaleDB        │
     │   - Hypertable for spans          │
     │   - Continuous aggregates         │
     └────────────────────────────────────┘
```

## Quick Start

### 1. Start the Database and Collector

```bash
docker-compose up -d
```

### 2. Install the SDK

**Python:**
```bash
pip install hikari-sdk[litellm]  # litellm provides pricing for 1,700+ models
```

**TypeScript:**
```bash
npm install @hikari/sdk
```

### 3. Instrument Your Code

**Python (zero-config):**
```python
import hikari

# Auto-instruments OpenAI, Anthropic, and Google clients
hikari.configure(collector_endpoint="http://localhost:8000")

# Your existing code works unchanged
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello!"}]
)
# Hikari automatically captures tokens, cost, and timing
```

**With explicit stages:**
```python
import hikari
from openai import OpenAI
from anthropic import Anthropic

hikari.configure(collector_endpoint="http://localhost:8000")

# Group multiple LLM calls into a single pipeline
with hikari.pipeline("document-processor"):
    # Stage 1: Classification
    hikari.set_stage("classify")
    openai_client = OpenAI()
    classification = openai_client.chat.completions.create(...)

    # Stage 2: Processing based on classification
    hikari.set_stage("process")
    anthropic_client = Anthropic()
    result = anthropic_client.messages.create(...)
```

### 4. Query Pipeline Costs

```bash
# Get cost breakdown for a pipeline
curl http://localhost:8000/v1/pipelines/{pipeline_id}/cost

# Response:
{
  "pipeline_id": "document-processor-abc123",
  "total_cost": 0.0234,
  "is_partial": false,
  "coverage_ratio": 1.0,
  "stages": [
    {
      "stage": "classify",
      "model": "gpt-4o",
      "provider": "openai",
      "tokens_input": 150,
      "tokens_output": 25,
      "cost_total": 0.0006
    },
    {
      "stage": "process",
      "model": "claude-3-5-sonnet-20241022",
      "provider": "anthropic",
      "tokens_input": 2000,
      "tokens_output": 1500,
      "cost_total": 0.0228
    }
  ]
}
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/traces` | POST | Ingest OTLP spans |
| `/v1/pipelines` | GET | List pipelines (with pagination) |
| `/v1/pipelines/{id}/cost` | GET | Get cost breakdown for a pipeline |
| `/v1/cost/trending` | GET | Get cost trends over time |
| `/v1/health` | GET | Health check |

## Pricing

Hikari uses a multi-tier pricing model:

1. **LiteLLM** (recommended): Install with `pip install hikari-sdk[litellm]` to get pricing for 1,700+ models across all major providers. Updates automatically with package upgrades.

2. **Environment override**: Set `HIKARI_PRICING_PATH` to a JSON file with custom pricing.

3. **User overrides**: Pass a `pricing` dict to `hikari.configure()`.

4. **Fallback**: Unknown models use conservative fallback pricing ($10/$30 per 1M tokens) to avoid underreporting.

## Design Philosophy

**Hikari is a mirror, not an advisor.**

- Surface cost facts with context. Never judge quality.
- Never recommend cheaper models. That's not Hikari's job.
- Show raw token counts alongside computed costs for verification.

**Graceful degradation over completeness gates.**

- Partial instrumentation is the norm, not the exception.
- Show what you know. Mark what you don't as "unknown cost."
- Report pipeline cost as "at least $X" when gaps exist (`is_partial: true`).

**OTel-native, not OTel-adjacent.**

- Use OpenTelemetry trace/span propagation as the wire protocol.
- Enrich with custom `hikari.*` attributes, don't replace standard semantics.
- Export Hikari spans to any OTel-compatible backend.

## Custom Span Attributes

All Hikari attributes are prefixed with `hikari.`:

| Attribute | Type | Description |
|-----------|------|-------------|
| `hikari.pipeline_id` | string | Explicit pipeline grouping (defaults to trace ID) |
| `hikari.stage` | string | Pipeline stage name |
| `hikari.model` | string | Model identifier (e.g., `gpt-4o`) |
| `hikari.provider` | string | Provider name (openai, anthropic, google) |
| `hikari.tokens.input` | int | Input token count |
| `hikari.tokens.output` | int | Output token count |
| `hikari.cost.input` | float | Computed input cost (USD) |
| `hikari.cost.output` | float | Computed output cost (USD) |
| `hikari.cost.total` | float | Computed total cost (USD) |

## Development

```bash
# Python SDK
cd sdk/python
uv sync --all-extras
uv run pytest

# Collector
cd collector
uv sync
uv run pytest

# Run everything locally
docker-compose up -d
```

## License

MIT
