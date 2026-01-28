/**
 * OTel SpanExporter that sends spans to the Hikari collector.
 *
 * Batches spans (default 100 or 5s flush interval), uses a bounded in-memory
 * queue (max 10,000 spans), drops oldest on overflow, and retries with
 * exponential backoff. Never raises exceptions to user code.
 */

import type { ReadableSpan } from "@opentelemetry/sdk-trace-base";
import { SpanExporter } from "@opentelemetry/sdk-trace-base";
import type { ExportResult } from "@opentelemetry/core";
import { ExportResultCode } from "@opentelemetry/core";

const RETRY_DELAYS_MS = [1000, 2000, 4000]; // exponential backoff

interface OtlpAttribute {
  key: string;
  value:
    | { intValue: string }
    | { doubleValue: number }
    | { stringValue: string }
    | { boolValue: boolean };
}

interface OtlpSpan {
  traceId: string;
  spanId: string;
  name: string;
  startTimeUnixNano: string;
  endTimeUnixNano: string;
  attributes: OtlpAttribute[];
}

interface OtlpPayload {
  resourceSpans: Array<{
    scopeSpans: Array<{
      spans: OtlpSpan[];
    }>;
  }>;
}

/**
 * Convert an OTel ReadableSpan to OTLP-compatible JSON.
 */
function spanToOtlp(span: ReadableSpan): OtlpSpan {
  const attrs: OtlpAttribute[] = [];

  if (span.attributes) {
    for (const [key, value] of Object.entries(span.attributes)) {
      if (typeof value === "number") {
        if (Number.isInteger(value)) {
          attrs.push({ key, value: { intValue: String(value) } });
        } else {
          attrs.push({ key, value: { doubleValue: value } });
        }
      } else if (typeof value === "string") {
        attrs.push({ key, value: { stringValue: value } });
      } else if (typeof value === "boolean") {
        attrs.push({ key, value: { boolValue: value } });
      }
    }
  }

  const context = span.spanContext();
  const traceId = context.traceId;
  const spanId = context.spanId;

  return {
    traceId,
    spanId,
    name: span.name,
    startTimeUnixNano: String(span.startTime[0] * 1_000_000_000 + span.startTime[1]),
    endTimeUnixNano: String(span.endTime[0] * 1_000_000_000 + span.endTime[1]),
    attributes: attrs,
  };
}

/**
 * Exports spans to the Hikari collector via HTTP POST.
 */
export class HikariSpanExporter implements SpanExporter {
  private readonly endpoint: string;
  private readonly maxQueueSize: number;
  private readonly batchSize: number;
  private readonly flushIntervalMs: number;
  private readonly queue: ReadableSpan[] = [];
  private shutdown_flag = false;
  private flushTimer: NodeJS.Timeout | null = null;

  constructor(config: {
    endpoint?: string;
    maxQueueSize?: number;
    batchSize?: number;
    flushIntervalMs?: number;
  } = {}) {
    this.endpoint = (config.endpoint ?? "http://localhost:8000").replace(/\/$/, "");
    this.maxQueueSize = config.maxQueueSize ?? 10_000;
    this.batchSize = config.batchSize ?? 100;
    this.flushIntervalMs = config.flushIntervalMs ?? 5000;

    this.startFlushTimer();
  }

  private startFlushTimer(): void {
    this.flushTimer = setInterval(() => {
      this.flushBatch().catch(() => {
        // Errors already logged in flushBatch
      });
    }, this.flushIntervalMs);

    // Don't prevent process exit
    if (this.flushTimer.unref) {
      this.flushTimer.unref();
    }
  }

  export(spans: ReadableSpan[], resultCallback: (result: ExportResult) => void): void {
    if (this.shutdown_flag) {
      resultCallback({ code: ExportResultCode.SUCCESS });
      return;
    }

    try {
      for (const span of spans) {
        // Add to queue, drop oldest if at capacity
        if (this.queue.length >= this.maxQueueSize) {
          this.queue.shift(); // Drop oldest
        }
        this.queue.push(span);
      }

      // Flush if batch size reached
      if (this.queue.length >= this.batchSize) {
        this.flushBatch().catch(() => {
          // Errors already logged
        });
      }
    } catch (err) {
      // Never throw to user code
      console.debug("Error enqueueing spans:", err);
    }

    resultCallback({ code: ExportResultCode.SUCCESS });
  }

  async shutdown(): Promise<void> {
    this.shutdown_flag = true;

    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }

    try {
      await this.flushBatch();
    } catch (err) {
      console.debug("Error during shutdown flush:", err);
    }
  }

  async forceFlush(): Promise<void> {
    try {
      await this.flushBatch();
    } catch (err) {
      console.debug("Error during force flush:", err);
    }
  }

  private async flushBatch(): Promise<void> {
    if (this.queue.length === 0) {
      return;
    }

    // Extract batch
    const batch = this.queue.splice(0, this.batchSize);
    if (batch.length === 0) {
      return;
    }

    const otlpSpans = batch.map(spanToOtlp);
    const payload: OtlpPayload = {
      resourceSpans: [
        {
          scopeSpans: [
            {
              spans: otlpSpans,
            },
          ],
        },
      ],
    };

    await this.sendWithRetry(payload);
  }

  private async sendWithRetry(payload: OtlpPayload): Promise<void> {
    const url = `${this.endpoint}/v1/traces`;
    const body = JSON.stringify(payload);

    for (let attempt = 0; attempt < RETRY_DELAYS_MS.length; attempt++) {
      try {
        const response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        });

        if (response.ok) {
          return;
        }

        console.debug(`Collector returned ${response.status} on attempt ${attempt + 1}`);
      } catch (err) {
        console.debug(`Send failed on attempt ${attempt + 1}:`, err);
      }

      // Wait before retry (except on last attempt)
      if (attempt < RETRY_DELAYS_MS.length - 1) {
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS_MS[attempt]));
      }
    }

    console.warn(`Dropped batch after ${RETRY_DELAYS_MS.length} retries`);
  }
}
