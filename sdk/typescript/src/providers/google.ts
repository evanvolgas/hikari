/**
 * Google GenAI provider monkey-patch.
 *
 * Target: `GenerativeModel.generateContent`
 * Min version: @google/generative-ai >= 0.3
 * Response token path: `response.usageMetadata.promptTokenCount`, `response.usageMetadata.candidatesTokenCount`
 * Model path: model instance's `model` property
 */

import { trace } from "@opentelemetry/api";
import * as attributes from "../attributes.js";
import { getPipelineId, getStage } from "../context.js";
import type { PricingModel } from "../pricing.js";

const MIN_VERSION = "0.3";
const PROVIDER_NAME = "google";

const tracer = trace.getTracer("hikari");

interface GoogleUsageMetadata {
  promptTokenCount?: number;
  candidatesTokenCount?: number;
}

interface GoogleResponse {
  usageMetadata?: GoogleUsageMetadata;
}

interface GenerativeModel {
  model: string;
  generateContent: (...args: unknown[]) => Promise<GoogleResponse>;
}

const originals = new Map<string, unknown>();

function extractTokens(response: GoogleResponse): [number | null, number | null] {
  const usage = response.usageMetadata;
  if (!usage) {
    return [null, null];
  }
  return [usage.promptTokenCount ?? null, usage.candidatesTokenCount ?? null];
}

function makeWrapper(
  original: (...args: unknown[]) => Promise<GoogleResponse>,
  modelName: string,
  pricing: PricingModel
): (...args: unknown[]) => Promise<GoogleResponse> {
  return async function (this: unknown, ...args: unknown[]): Promise<GoogleResponse> {
    const spanName = "google.generativeai.generate_content";
    const stage = getStage() ?? spanName;

    return tracer.startActiveSpan(spanName, async (span) => {
      try {
        const response = await original.apply(this, args);

        try {
          const [inputTokens, outputTokens] = extractTokens(response);
          const pipelineId = getPipelineId();

          if (pipelineId) {
            span.setAttribute(attributes.PIPELINE_ID, pipelineId);
          }
          span.setAttribute(attributes.STAGE, stage);
          span.setAttribute(attributes.MODEL, modelName);
          span.setAttribute(attributes.PROVIDER, PROVIDER_NAME);

          if (inputTokens !== null) {
            span.setAttribute(attributes.TOKENS_INPUT, inputTokens);
          }
          if (outputTokens !== null) {
            span.setAttribute(attributes.TOKENS_OUTPUT, outputTokens);
          }

          const { inputCost, outputCost, totalCost } = pricing.computeCost(
            PROVIDER_NAME,
            modelName,
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
 * Apply monkey-patch to Google GenAI client methods.
 *
 * @param pricing - The pricing model to use for cost computation
 * @returns `true` if patch was applied, `false` if skipped
 */
export function patch(pricing: PricingModel): boolean {
  try {
    // Dynamic import to avoid hard dependency
    const genai = require("@google/generative-ai");
    const version = genai.VERSION ?? genai.default?.VERSION ?? "0.0.0";

    // Version check
    const [major, minor] = version.split(".").map((v: string) => parseInt(v, 10));
    const [minMajor, minMinor] = MIN_VERSION.split(".").map((v) => parseInt(v, 10));

    if ((major ?? 0) < (minMajor ?? 0) || ((major ?? 0) === (minMajor ?? 0) && (minor ?? 0) < (minMinor ?? 0))) {
      console.warn(`@google/generative-ai version ${version} < ${MIN_VERSION}, skipping`);
      return false;
    }

    // Patch the GenerativeModel class prototype
    // The challenge: we need to patch instances, not the class, because model name varies
    // Solution: patch the GoogleGenerativeAI.getGenerativeModel method to return patched instances
    const GoogleGenerativeAI = genai.GoogleGenerativeAI ?? genai.default?.GoogleGenerativeAI;
    if (!GoogleGenerativeAI) {
      console.warn("GoogleGenerativeAI class not found, skipping");
      return false;
    }

    const proto = GoogleGenerativeAI.prototype;
    const originalGetModel = proto.getGenerativeModel;

    if (!originalGetModel) {
      console.warn("getGenerativeModel method not found, skipping");
      return false;
    }

    originals.set("getGenerativeModel", originalGetModel);

    proto.getGenerativeModel = function (this: unknown, ...args: unknown[]): GenerativeModel {
      const model = originalGetModel.apply(this, args) as GenerativeModel;
      const modelName = model.model;

      // Patch the instance's generateContent method
      const originalGenerate = model.generateContent.bind(model);
      model.generateContent = makeWrapper(
        originalGenerate as (...args: unknown[]) => Promise<GoogleResponse>,
        modelName,
        pricing
      );

      return model;
    };

    console.info(`Patched @google/generative-ai ${version}`);
    return true;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "MODULE_NOT_FOUND") {
      console.debug("@google/generative-ai not installed, skipping");
      return false;
    }
    console.warn("Failed to patch @google/generative-ai:", err);
    return false;
  }
}

/**
 * Restore original Google GenAI methods.
 */
export function unpatch(): void {
  try {
    const genai = require("@google/generative-ai");
    const GoogleGenerativeAI = genai.GoogleGenerativeAI ?? genai.default?.GoogleGenerativeAI;

    if (!GoogleGenerativeAI) {
      return;
    }

    const proto = GoogleGenerativeAI.prototype;
    const original = originals.get("getGenerativeModel");

    if (original) {
      proto.getGenerativeModel = original;
      originals.delete("getGenerativeModel");
    }
  } catch {
    // Ignore if google not installed
  }
}
