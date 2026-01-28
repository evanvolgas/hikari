/**
 * Anthropic provider monkey-patch.
 *
 * Target: `Anthropic.messages.create`
 * Min version: @anthropic-ai/sdk >= 0.18
 * Response token path: `response.usage.input_tokens`, `response.usage.output_tokens`
 * Model path: `response.model` (or request kwarg `model`)
 */

import { trace } from "@opentelemetry/api";
import * as attributes from "../attributes.js";
import { getPipelineId, getStage } from "../context.js";
import type { PricingModel } from "../pricing.js";

const MIN_VERSION = "0.18";
const PROVIDER_NAME = "anthropic";

const tracer = trace.getTracer("hikari");

interface AnthropicUsage {
  input_tokens?: number;
  output_tokens?: number;
}

interface AnthropicResponse {
  usage?: AnthropicUsage;
  model?: string;
}

const originals = new Map<string, unknown>();

function extractTokens(response: AnthropicResponse): [number | null, number | null] {
  const usage = response.usage;
  if (!usage) {
    return [null, null];
  }
  return [usage.input_tokens ?? null, usage.output_tokens ?? null];
}

function extractModel(response: AnthropicResponse, kwargs: Record<string, unknown>): string {
  return response.model ?? (kwargs.model as string) ?? "unknown";
}

function makeWrapper(
  original: (...args: unknown[]) => Promise<AnthropicResponse>,
  pricing: PricingModel
): (...args: unknown[]) => Promise<AnthropicResponse> {
  return async function (this: unknown, ...args: unknown[]): Promise<AnthropicResponse> {
    const spanName = "anthropic.messages.create";
    const stage = getStage() ?? spanName;

    return tracer.startActiveSpan(spanName, async (span) => {
      try {
        const response = await original.apply(this, args);

        try {
          const [inputTokens, outputTokens] = extractTokens(response);
          const kwargs = (args[0] as Record<string, unknown>) ?? {};
          const model = extractModel(response, kwargs);
          const pipelineId = getPipelineId();

          if (pipelineId) {
            span.setAttribute(attributes.PIPELINE_ID, pipelineId);
          }
          span.setAttribute(attributes.STAGE, stage);
          span.setAttribute(attributes.MODEL, model);
          span.setAttribute(attributes.PROVIDER, PROVIDER_NAME);

          if (inputTokens !== null) {
            span.setAttribute(attributes.TOKENS_INPUT, inputTokens);
          }
          if (outputTokens !== null) {
            span.setAttribute(attributes.TOKENS_OUTPUT, outputTokens);
          }

          const { inputCost, outputCost, totalCost } = pricing.computeCost(
            PROVIDER_NAME,
            model,
            inputTokens,
            outputTokens
          );

          if (inputCost !== null) {
            span.setAttribute(attributes.COST_INPUT, inputCost);
          }
          if (outputCost !== null) {
            span.setAttribute(attributes.COST_OUTPUT, outputCost);
          }
          if (totalCost !== null) {
            span.setAttribute(attributes.COST_TOTAL, totalCost);
          }
        } catch (err) {
          console.debug("Failed to set span attributes:", err);
        }

        span.end();
        return response;
      } catch (err) {
        span.end();
        throw err;
      }
    });
  };
}

/**
 * Apply monkey-patch to Anthropic client methods.
 *
 * @param pricing - The pricing model to use for cost computation
 * @returns `true` if patch was applied, `false` if skipped
 */
export function patch(pricing: PricingModel): boolean {
  try {
    // Dynamic import to avoid hard dependency
    const anthropic = require("@anthropic-ai/sdk");
    const version = anthropic.VERSION ?? anthropic.default?.VERSION ?? "0.0.0";

    // Version check
    const [major, minor] = version.split(".").map((v: string) => parseInt(v, 10));
    const [minMajor, minMinor] = MIN_VERSION.split(".").map((v) => parseInt(v, 10));

    if ((major ?? 0) < (minMajor ?? 0) || ((major ?? 0) === (minMajor ?? 0) && (minor ?? 0) < (minMinor ?? 0))) {
      console.warn(`@anthropic-ai/sdk version ${version} < ${MIN_VERSION}, skipping`);
      return false;
    }

    // Patch the Anthropic class prototype
    const Anthropic = anthropic.default ?? anthropic;
    const proto = Anthropic.prototype;

    if (!proto?.messages) {
      console.warn("Anthropic client structure not recognized, skipping");
      return false;
    }

    const original = proto.messages.create.bind(proto.messages);
    originals.set("create", original);

    proto.messages.create = makeWrapper(
      original as (...args: unknown[]) => Promise<AnthropicResponse>,
      pricing
    );

    console.info(`Patched @anthropic-ai/sdk ${version}`);
    return true;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "MODULE_NOT_FOUND") {
      console.debug("@anthropic-ai/sdk not installed, skipping");
      return false;
    }
    console.warn("Failed to patch @anthropic-ai/sdk:", err);
    return false;
  }
}

/**
 * Restore original Anthropic methods.
 */
export function unpatch(): void {
  try {
    const anthropic = require("@anthropic-ai/sdk");
    const Anthropic = anthropic.default ?? anthropic;
    const proto = Anthropic.prototype;

    const original = originals.get("create");
    if (original && proto?.messages) {
      proto.messages.create = original;
      originals.delete("create");
    }
  } catch {
    // Ignore if anthropic not installed
  }
}
