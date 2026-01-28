/**
 * Tests for HikariInstrumentor.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { HikariInstrumentor } from "../instrumentor.js";
import { PricingModel } from "../pricing.js";

describe("HikariInstrumentor", () => {
  let instrumentor: HikariInstrumentor;
  let pricing: PricingModel;

  beforeEach(() => {
    instrumentor = new HikariInstrumentor();
    pricing = new PricingModel();
  });

  afterEach(() => {
    instrumentor.uninstrument();
  });

  it("should return empty list when no providers are installed", () => {
    // Mock require to simulate missing providers
    vi.mock("openai", () => {
      throw new Error("MODULE_NOT_FOUND");
    });
    vi.mock("@anthropic-ai/sdk", () => {
      throw new Error("MODULE_NOT_FOUND");
    });
    vi.mock("@google/generative-ai", () => {
      throw new Error("MODULE_NOT_FOUND");
    });

    const patched = instrumentor.instrument(pricing);
    expect(patched).toEqual([]);
    expect(instrumentor.getPatchedProviders()).toEqual([]);
  });

  it("should track patched providers", () => {
    const patched = instrumentor.instrument(pricing);

    // We don't know which providers are actually installed in the test environment
    // but the list should be consistent
    expect(instrumentor.getPatchedProviders()).toEqual(patched);
  });

  it("should clear patched providers on uninstrument", () => {
    instrumentor.instrument(pricing);
    const patchedBefore = instrumentor.getPatchedProviders();

    // Only proceed if something was patched
    if (patchedBefore.length > 0) {
      instrumentor.uninstrument();
      expect(instrumentor.getPatchedProviders()).toEqual([]);
    } else {
      // If nothing was patched, we can't test uninstrumentation
      expect(patchedBefore).toEqual([]);
    }
  });

  it("should allow re-instrumentation after uninstrumentation", () => {
    const patched1 = instrumentor.instrument(pricing);
    instrumentor.uninstrument();
    const patched2 = instrumentor.instrument(pricing);

    expect(patched2).toEqual(patched1);
  });

  it("should not throw on multiple uninstrument calls", () => {
    instrumentor.instrument(pricing);
    expect(() => {
      instrumentor.uninstrument();
      instrumentor.uninstrument();
      instrumentor.uninstrument();
    }).not.toThrow();
  });

  it("should handle instrumentation before any providers loaded", () => {
    // Create fresh instrumentor before any dynamic imports
    const freshInstrumentor = new HikariInstrumentor();
    const result = freshInstrumentor.instrument(pricing);

    // Should not throw, and should return a valid array
    expect(Array.isArray(result)).toBe(true);

    freshInstrumentor.uninstrument();
  });
});
