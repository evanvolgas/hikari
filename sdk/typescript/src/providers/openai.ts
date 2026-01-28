/**
 * OpenAI provider monkey-patch.
 *
 * Target: `OpenAI.chat.completions.create`
 * Min version: openai >= 4.0
 * Response token path: `response.usage.prompt_tokens`, `response.usage.completion_tokens`
 * Model path: `response.model` (or request kwarg `model`)
 */

import { trace } from "@opentelemetry/api";
import * as attributes from "../attributes.js";
import { getPipelineId, getStage } from "../context.js";
import type { PricingModel } from "../pricing.js";

const MIN_VERSION = "4.0";
const PROVIDER_NAME = "openai";

const tracer = trace.getTracer("hikari");

interface OpenAIUsage {
  prompt_tokens?: number;
  completion_tokens?: number;
}

interface OpenAIResponse {
  usage?: OpenAIUsage;
  model?: string;
}

interface OpenAIClient {
  chat: {
    completions: {
      create: (...args: unknown[]) => Promise<OpenAIResponse>;
    };
  };
}

const originals = new Map<string, unknown>();

function extractTokens(response: OpenAIResponse): [number | null, number | null] {
  const usage = response.usage;
  if (!usage) {
    return [null, null];
  }
  return [usage.prompt_tokens ?? null, usage.completion_tokens ?? null];
}

function extractModel(response: OpenAIResponse, kwargs: Record<string, unknown>): string {
  return response.model ?? (kwargs.model as string) ?? "unknown";
}

function makeWrapper(
  original: (...args: unknown[]) => Promise<OpenAIResponse>,
  pricing: PricingModel
): (...args: unknown[]) => Promise<OpenAIResponse> {
  return async function (this: unknown, ...args: unknown[]): Promise<OpenAIResponse> {
    const spanName = "openai.chat.completions.create";
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
 * Apply monkey-patch to OpenAI client methods.
 *
 * @param pricing - The pricing model to use for cost computation
 * @returns `true` if patch was applied, `false` if skipped
 */
export function patch(pricing: PricingModel): boolean {
  try {
    // Dynamic import to avoid hard dependency
    const openai = require("openai");
    const version = openai.VERSION ?? openai.default?.VERSION ?? "0.0.0";

    // Version check
    const major = parseInt(version.split(".")[0] ?? "0", 10);
    if (major < 4) {
      console.warn(`openai version ${version} < ${MIN_VERSION}, skipping`);
      return false;
    }

    // Patch the OpenAI class prototype
    const OpenAI = openai.default ?? openai;
    const proto = OpenAI.prototype;

    if (!proto?.chat?.completions) {
      console.warn("OpenAI client structure not recognized, skipping");
      return false;
    }

    const original = proto.chat.completions.create.bind(proto.chat.completions);
    originals.set("create", original);

    proto.chat.completions.create = makeWrapper(
      original as (...args: unknown[]) => Promise<OpenAIResponse>,
      pricing
    );

    console.info(`Patched openai ${version}`);
    return true;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "MODULE_NOT_FOUND") {
      console.debug("openai not installed, skipping");
      return false;
    }
    console.warn("Failed to patch openai:", err);
    return false;
  }
}

/**
 * Restore original OpenAI methods.
 */
export function unpatch(): void {
  try {
    const openai = require("openai");
    const OpenAI = openai.default ?? openai;
    const proto = OpenAI.prototype;

    const original = originals.get("create");
    if (original && proto?.chat?.completions) {
      proto.chat.completions.create = original;
      originals.delete("create");
    }
  } catch {
    // Ignore if openai not installed
  }
}
