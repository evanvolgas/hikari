# Hikari - Claude Code Configuration

## Project Overview

Hikari is an open-source, OpenTelemetry-based LLM pipeline cost intelligence tool. It instruments multi-step LLM pipelines and provides end-to-end cost decomposition by stage -- something no existing observability tool does.

Named after the Japanese word for "light" (光), consistent with Ashita AI's naming convention.

## Architecture

See `docs/spec.md` for the full specification.

**Core Flow**: SDK auto-instruments provider clients → spans enriched with Hikari cost attributes → async ingestion → PostgreSQL/TimescaleDB → pipeline cost aggregation and trending

**Key Abstraction**: A *pipeline* = all spans sharing a trace ID (default) or an explicit `hikari.pipeline_id` span attribute (override).

## Tech Stack

- **Python SDK**: Python 3.11+, OpenTelemetry SDK, monkey-patching for OpenAI/Anthropic/Google clients
- **TypeScript SDK**: Node.js 20+, TypeScript 5.x (strict mode), OpenTelemetry JS SDK
- **Collector/API**: Python (FastAPI), async span ingestion
- **Storage**: PostgreSQL 16+ with TimescaleDB extension
- **Testing**: pytest (Python), Vitest (TypeScript)

## Project Structure

```
hikari/
  docs/           # Specification and architecture docs
  sdk/
    python/       # Python SDK (hikari-python)
    typescript/   # TypeScript SDK (hikari-js)
  collector/      # OTLP-compatible span collector and API
  migrations/     # TimescaleDB schema and migrations
  tests/          # Integration tests
```

## Commands

```bash
# Python SDK
cd sdk/python
uv run pytest               # Run tests
uv run mypy src/             # Type check
uv run ruff check src/       # Lint

# TypeScript SDK
cd sdk/typescript
npm run test                 # Run tests
npm run typecheck            # Type check
npm run lint                 # Lint
npm run build                # Compile

# Collector
cd collector
uv run pytest                # Run tests
uv run alembic upgrade head  # Run migrations
```

## Custom Span Attributes

All Hikari attributes are prefixed with `hikari.`:

| Attribute | Type | Required | Description |
|-----------|------|----------|-------------|
| `hikari.pipeline_id` | string | No | Explicit pipeline grouping (overrides trace ID) |
| `hikari.stage` | string | Yes | Pipeline stage name |
| `hikari.model` | string | Yes | Model identifier (e.g., `gpt-4`, `claude-3-haiku`) |
| `hikari.provider` | string | Yes | Provider name (openai, anthropic, google) |
| `hikari.tokens.input` | int | Yes | Input token count |
| `hikari.tokens.output` | int | Yes | Output token count |
| `hikari.cost.input` | float | No | Computed input cost (USD) |
| `hikari.cost.output` | float | No | Computed output cost (USD) |
| `hikari.cost.total` | float | No | Computed total cost (USD) |

## Code Conventions

### File Organization

- Python: `src/hikari/` package structure, `tests/` mirroring source
- TypeScript: `src/` with barrel exports, `__tests__/` co-located
- Migrations: numbered sequential files in `migrations/`

### Naming Conventions

- Python files: `snake_case.py`
- TypeScript files: `kebab-case.ts`
- Types/Interfaces: `PascalCase`
- Functions: `snake_case` (Python), `camelCase` (TypeScript)
- Constants: `SCREAMING_SNAKE_CASE`
- Span attributes: `hikari.dot.separated`

### Code Style

- Python: strict mypy, ruff for linting and formatting, explicit type annotations
- TypeScript: strict mode, no `any`, explicit return types, Zod for external inputs
- Both: prefer explicit over clever, no abbreviations in public APIs

### Key Design Principles

**Hikari is a mirror, not an advisor.**

- Surface cost facts with context. Never judge quality.
- Never recommend cheaper models. That is Conduit's job.
- Never evaluate output quality. That is Arbiter's job.
- Show raw token counts alongside computed costs so users can verify independently.

**Graceful degradation over completeness gates.**

- Partial instrumentation is the norm, not the exception.
- Show what you know. Mark what you don't as "unknown cost."
- Report pipeline cost as "at least $X" when gaps exist.

**OTel-native, not OTel-adjacent.**

- Use OpenTelemetry trace/span propagation as the wire protocol.
- Enrich with custom attributes, don't replace standard semantics.
- Users can export Hikari spans to any OTel-compatible backend.

### Error Handling

- Use custom exception classes with error codes
- Log errors with context (trace_id, pipeline_id, stage)
- Never swallow errors silently
- SDK errors must never crash the user's application -- fail open, log the error

### Testing

- Unit tests for all cost computation logic
- Integration tests for auto-instrumentation of each provider
- Property-based tests for cost aggregation edge cases (partial data, missing spans, concurrent pipelines)
- Test with real provider response shapes (mocked, not fabricated)

## Boundaries

### Always Do (No Permission Needed)

- Run tests before committing
- Type check before committing
- Lint before committing
- Keep SDK instrumentation zero-config (auto-instrument by default)
- Surface raw data alongside computed values
- Use async I/O for all span ingestion paths

### Ask First

- Adding a new span attribute to the `hikari.*` namespace
- Changing the pipeline cost aggregation logic
- Adding a new provider integration
- Modifying the pricing model schema
- Changing retention policy defaults

### Never Do

- Evaluate output quality or judge model selection
- Recommend cheaper models or routing changes
- Add proxy-based instrumentation (latency penalty)
- Block the user's hot path for span processing
- Commit API keys, secrets, or provider credentials
- Log prompt content or LLM outputs (cost metadata only)
- Add dependencies on other Ashita tools (Arbiter, Conduit, Engram, Tessera)
