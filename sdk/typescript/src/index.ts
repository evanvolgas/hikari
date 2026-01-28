/**
 * Hikari TypeScript SDK - OpenTelemetry-based LLM pipeline cost intelligence.
 *
 * Usage:
 * ```typescript
 * import { configure, setPipelineId, setStage, shutdown } from 'hikari-js';
 *
 * // Initialize Hikari instrumentation
 * configure({
 *   collectorEndpoint: 'http://localhost:8000',
 *   pricing: {
 *     'openai/custom-model': {
 *       inputCostPerToken: 0.000001,
 *       outputCostPerToken: 0.000002,
 *     },
 *   },
 * });
 *
 * // Use in your pipeline
 * setPipelineId('user-request-123');
 * setStage('document-retrieval');
 *
 * // ... your LLM calls (auto-instrumented) ...
 *
 * // Graceful shutdown
 * await shutdown();
 * ```
 */

import { NodeTracerProvider } from "@opentelemetry/sdk-trace-node";
import { BatchSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { HikariSpanExporter } from "./exporter.js";
import { PricingModel, type ModelPricing } from "./pricing.js";
import { HikariInstrumentor } from "./instrumentor.js";
import { setPipelineId as setContextPipelineId, setStage as setContextStage } from "./context.js";

/**
 * Configuration options for Hikari.
 */
export interface HikariConfig {
  /**
   * Custom pricing overrides.
   * Keys are in format `{provider}/{model}` (e.g., `openai/gpt-4o`)
   */
  pricing?: Record<string, ModelPricing>;

  /**
   * Hikari collector endpoint.
   * @default "http://localhost:8000"
   */
  collectorEndpoint?: string;

  /**
   * Number of spans to batch before sending.
   * @default 100
   */
  batchSize?: number;

  /**
   * Maximum time in milliseconds to wait before flushing a batch.
   * @default 5000
   */
  flushIntervalMs?: number;

  /**
   * Maximum number of spans to queue before dropping oldest.
   * @default 10_000
   */
  maxQueueSize?: number;
}

let tracerProvider: NodeTracerProvider | null = null;
let spanExporter: HikariSpanExporter | null = null;
let instrumentor: HikariInstrumentor | null = null;

/**
 * Configure and initialize Hikari instrumentation.
 *
 * This function:
 * - Loads pricing model (bundled defaults + user overrides)
 * - Initializes OpenTelemetry tracer provider
 * - Sets up the Hikari span exporter
 * - Auto-instruments available LLM provider clients
 *
 * @param config - Configuration options
 */
export function configure(config?: HikariConfig): void {
  if (tracerProvider) {
    console.warn("Hikari already configured. Ignoring duplicate configure() call.");
    return;
  }

  // Initialize pricing model
  const pricing = new PricingModel(config?.pricing);

  // Initialize span exporter
  spanExporter = new HikariSpanExporter({
    endpoint: config?.collectorEndpoint,
    batchSize: config?.batchSize,
    flushIntervalMs: config?.flushIntervalMs,
    maxQueueSize: config?.maxQueueSize,
  });

  // Initialize OpenTelemetry tracer provider
  tracerProvider = new NodeTracerProvider();
  tracerProvider.addSpanProcessor(new BatchSpanProcessor(spanExporter));
  tracerProvider.register();

  // Auto-instrument providers
  instrumentor = new HikariInstrumentor();
  const patched = instrumentor.instrument(pricing);

  if (patched.length > 0) {
    console.info(`Hikari instrumented: ${patched.join(", ")}`);
  } else {
    console.info("Hikari initialized (no LLM providers detected)");
  }
}

/**
 * Set the pipeline ID for the current async context.
 *
 * This overrides the default trace ID-based pipeline grouping.
 *
 * @param pipelineId - The pipeline identifier
 */
export function setPipelineId(pipelineId: string): void {
  setContextPipelineId(pipelineId);
}

/**
 * Set the stage name for the current async context.
 *
 * This is used to decompose pipeline cost by stage.
 *
 * @param stage - The stage name
 */
export function setStage(stage: string): void {
  setContextStage(stage);
}

/**
 * Gracefully shut down Hikari instrumentation.
 *
 * Flushes remaining spans and stops background threads.
 * Should be called before process exit.
 */
export async function shutdown(): Promise<void> {
  if (instrumentor) {
    instrumentor.uninstrument();
    instrumentor = null;
  }

  if (spanExporter) {
    await spanExporter.shutdown();
    spanExporter = null;
  }

  if (tracerProvider) {
    await tracerProvider.shutdown();
    tracerProvider = null;
  }
}

// Re-export types
export type { ModelPricing } from "./pricing.js";
