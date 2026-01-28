/**
 * Tests for provider instrumentation.
 *
 * Uses in-memory span exporter to verify that provider methods
 * are correctly patched and emit spans with hikari.* attributes.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { InMemorySpanExporter, SimpleSpanProcessor } from "@opentelemetry/sdk-trace-base";
import { NodeTracerProvider } from "@opentelemetry/sdk-trace-node";
import { PricingModel } from "../pricing.js";
import * as attributes from "../attributes.js";

describe("Provider instrumentation", () => {
  let provider: NodeTracerProvider;
  let exporter: InMemorySpanExporter;
  let pricing: PricingModel;

  beforeEach(() => {
    // Set up in-memory span exporter
    exporter = new InMemorySpanExporter();
    provider = new NodeTracerProvider();
    provider.addSpanProcessor(new SimpleSpanProcessor(exporter));
    provider.register();

    pricing = new PricingModel();
  });

  afterEach(() => {
    exporter.reset();
    provider.shutdown();
  });

  describe("OpenAI", () => {
    it("should create span with hikari attributes", async () => {
      try {
        const { patch, unpatch } = await import("../providers/openai.js");
        const patched = patch(pricing);

        if (!patched) {
          console.log("OpenAI not installed, skipping test");
          return;
        }

        try {
          // Mock the OpenAI client
          const openai = require("openai");
          const OpenAI = openai.default ?? openai;

          const mockResponse = {
            model: "gpt-4o",
            usage: {
              prompt_tokens: 100,
              completion_tokens: 50,
            },
          };

          // Create a mock client
          const client = new OpenAI({ apiKey: "test-key" });

          // Mock the actual API call
          const originalCreate = client.chat.completions.create;
          client.chat.completions.create = vi.fn().mockResolvedValue(mockResponse);

          // Call the wrapped method
          await client.chat.completions.create({ model: "gpt-4o", messages: [] });

          // Wait for span to be exported
          await provider.forceFlush();

          // Verify span was created
          const spans = exporter.getFinishedSpans();
          expect(spans.length).toBeGreaterThan(0);

          const span = spans[0];
          expect(span?.name).toBe("openai.chat.completions.create");

          // Verify hikari attributes
          const attrs = span?.attributes;
          expect(attrs?.[attributes.PROVIDER]).toBe("openai");
          expect(attrs?.[attributes.MODEL]).toBe("gpt-4o");
          expect(attrs?.[attributes.TOKENS_INPUT]).toBe(100);
          expect(attrs?.[attributes.TOKENS_OUTPUT]).toBe(50);
          expect(attrs?.[attributes.COST_INPUT]).toBeDefined();
          expect(attrs?.[attributes.COST_OUTPUT]).toBeDefined();
          expect(attrs?.[attributes.COST_TOTAL]).toBeDefined();

          // Verify cost computation
          const expectedInputCost = 0.0000025 * 100;
          const expectedOutputCost = 0.00001 * 50;
          expect(attrs?.[attributes.COST_INPUT]).toBe(expectedInputCost);
          expect(attrs?.[attributes.COST_OUTPUT]).toBe(expectedOutputCost);
          expect(attrs?.[attributes.COST_TOTAL]).toBe(expectedInputCost + expectedOutputCost);
        } finally {
          unpatch();
        }
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === "MODULE_NOT_FOUND") {
          console.log("OpenAI not installed, skipping test");
        } else {
          throw err;
        }
      }
    });

    it("should not throw on provider errors", async () => {
      try {
        const { patch, unpatch } = await import("../providers/openai.js");
        const patched = patch(pricing);

        if (!patched) {
          return;
        }

        try {
          const openai = require("openai");
          const OpenAI = openai.default ?? openai;
          const client = new OpenAI({ apiKey: "test-key" });

          // Mock error response
          client.chat.completions.create = vi.fn().mockRejectedValue(new Error("API Error"));

          // Should propagate the error but not crash
          await expect(
            client.chat.completions.create({ model: "gpt-4o", messages: [] })
          ).rejects.toThrow("API Error");
        } finally {
          unpatch();
        }
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code !== "MODULE_NOT_FOUND") {
          throw err;
        }
      }
    });
  });

  describe("Anthropic", () => {
    it("should create span with hikari attributes", async () => {
      try {
        const { patch, unpatch } = await import("../providers/anthropic.js");
        const patched = patch(pricing);

        if (!patched) {
          console.log("Anthropic not installed, skipping test");
          return;
        }

        try {
          const anthropic = require("@anthropic-ai/sdk");
          const Anthropic = anthropic.default ?? anthropic;

          const mockResponse = {
            model: "claude-3-haiku-20240307",
            usage: {
              input_tokens: 100,
              output_tokens: 50,
            },
          };

          const client = new Anthropic({ apiKey: "test-key" });
          client.messages.create = vi.fn().mockResolvedValue(mockResponse);

          await client.messages.create({ model: "claude-3-haiku-20240307", messages: [] });

          await provider.forceFlush();

          const spans = exporter.getFinishedSpans();
          expect(spans.length).toBeGreaterThan(0);

          const span = spans[0];
          expect(span?.name).toBe("anthropic.messages.create");

          const attrs = span?.attributes;
          expect(attrs?.[attributes.PROVIDER]).toBe("anthropic");
          expect(attrs?.[attributes.MODEL]).toBe("claude-3-haiku-20240307");
          expect(attrs?.[attributes.TOKENS_INPUT]).toBe(100);
          expect(attrs?.[attributes.TOKENS_OUTPUT]).toBe(50);
          expect(attrs?.[attributes.COST_INPUT]).toBeDefined();
          expect(attrs?.[attributes.COST_OUTPUT]).toBeDefined();
          expect(attrs?.[attributes.COST_TOTAL]).toBeDefined();
        } finally {
          unpatch();
        }
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === "MODULE_NOT_FOUND") {
          console.log("Anthropic not installed, skipping test");
        } else {
          throw err;
        }
      }
    });
  });

  describe("Google", () => {
    it("should create span with hikari attributes", async () => {
      try {
        const { patch, unpatch } = await import("../providers/google.js");
        const patched = patch(pricing);

        if (!patched) {
          console.log("Google GenAI not installed, skipping test");
          return;
        }

        try {
          const genai = require("@google/generative-ai");
          const GoogleGenerativeAI = genai.GoogleGenerativeAI ?? genai.default?.GoogleGenerativeAI;

          const mockResponse = {
            usageMetadata: {
              promptTokenCount: 100,
              candidatesTokenCount: 50,
            },
          };

          const client = new GoogleGenerativeAI("test-key");
          const model = client.getGenerativeModel({ model: "gemini-1.5-flash" });

          // Mock the generateContent method
          const originalGenerate = model.generateContent;
          model.generateContent = vi.fn().mockResolvedValue(mockResponse);

          await model.generateContent("test prompt");

          await provider.forceFlush();

          const spans = exporter.getFinishedSpans();
          expect(spans.length).toBeGreaterThan(0);

          const span = spans[0];
          expect(span?.name).toBe("google.generativeai.generate_content");

          const attrs = span?.attributes;
          expect(attrs?.[attributes.PROVIDER]).toBe("google");
          expect(attrs?.[attributes.MODEL]).toBe("gemini-1.5-flash");
          expect(attrs?.[attributes.TOKENS_INPUT]).toBe(100);
          expect(attrs?.[attributes.TOKENS_OUTPUT]).toBe(50);
          expect(attrs?.[attributes.COST_INPUT]).toBeDefined();
          expect(attrs?.[attributes.COST_OUTPUT]).toBeDefined();
          expect(attrs?.[attributes.COST_TOTAL]).toBeDefined();
        } finally {
          unpatch();
        }
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === "MODULE_NOT_FOUND") {
          console.log("Google GenAI not installed, skipping test");
        } else {
          throw err;
        }
      }
    });
  });
});
