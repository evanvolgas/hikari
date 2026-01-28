/**
 * Tests for PricingModel.
 */

import { describe, it, expect } from "vitest";
import { PricingModel } from "../pricing.js";

describe("PricingModel", () => {
  it("should load default pricing", () => {
    const pricing = new PricingModel();
    const result = pricing.get("openai", "gpt-4o");

    expect(result).not.toBeNull();
    expect(result?.inputCostPerToken).toBe(0.0000025);
    expect(result?.outputCostPerToken).toBe(0.00001);
  });

  it("should return null for unknown model", () => {
    const pricing = new PricingModel();
    const result = pricing.get("openai", "unknown-model");

    expect(result).toBeNull();
  });

  it("should compute cost with known model", () => {
    const pricing = new PricingModel();
    const result = pricing.computeCost("openai", "gpt-4o", 1000, 500);

    expect(result.inputCost).toBe(0.0000025 * 1000);
    expect(result.outputCost).toBe(0.00001 * 500);
    expect(result.totalCost).toBe(0.0000025 * 1000 + 0.00001 * 500);
  });

  it("should return null costs with null tokens", () => {
    const pricing = new PricingModel();
    const result = pricing.computeCost("openai", "gpt-4o", null, null);

    expect(result.inputCost).toBeNull();
    expect(result.outputCost).toBeNull();
    expect(result.totalCost).toBeNull();
  });

  it("should return null total cost when input tokens are null", () => {
    const pricing = new PricingModel();
    const result = pricing.computeCost("openai", "gpt-4o", null, 500);

    expect(result.inputCost).toBeNull();
    expect(result.outputCost).toBe(0.00001 * 500);
    expect(result.totalCost).toBeNull(); // Cannot compute total with missing input
  });

  it("should return null total cost when output tokens are null", () => {
    const pricing = new PricingModel();
    const result = pricing.computeCost("openai", "gpt-4o", 1000, null);

    expect(result.inputCost).toBe(0.0000025 * 1000);
    expect(result.outputCost).toBeNull();
    expect(result.totalCost).toBeNull(); // Cannot compute total with missing output
  });

  it("should return null costs for unknown model", () => {
    const pricing = new PricingModel();
    const result = pricing.computeCost("openai", "unknown-model", 1000, 500);

    expect(result.inputCost).toBeNull();
    expect(result.outputCost).toBeNull();
    expect(result.totalCost).toBeNull();
  });

  it("should update pricing at runtime", () => {
    const pricing = new PricingModel();

    // Before update
    let result = pricing.get("custom", "model-1");
    expect(result).toBeNull();

    // Update
    pricing.update("custom/model-1", 0.000001, 0.000002);

    // After update
    result = pricing.get("custom", "model-1");
    expect(result).not.toBeNull();
    expect(result?.inputCostPerToken).toBe(0.000001);
    expect(result?.outputCostPerToken).toBe(0.000002);

    // Compute with updated pricing
    const costResult = pricing.computeCost("custom", "model-1", 1000, 500);
    expect(costResult.inputCost).toBe(0.000001 * 1000);
    expect(costResult.outputCost).toBe(0.000002 * 500);
    expect(costResult.totalCost).toBe(0.000001 * 1000 + 0.000002 * 500);
  });

  it("should override default pricing with constructor overrides", () => {
    const pricing = new PricingModel({
      "openai/gpt-4o": {
        inputCostPerToken: 0.0000099,
        outputCostPerToken: 0.0000199,
      },
    });

    const result = pricing.get("openai", "gpt-4o");
    expect(result?.inputCostPerToken).toBe(0.0000099);
    expect(result?.outputCostPerToken).toBe(0.0000199);
  });

  it("should include all bundled providers", () => {
    const pricing = new PricingModel();

    expect(pricing.get("openai", "gpt-4o")).not.toBeNull();
    expect(pricing.get("openai", "gpt-4o-mini")).not.toBeNull();
    expect(pricing.get("anthropic", "claude-3-5-sonnet-20241022")).not.toBeNull();
    expect(pricing.get("anthropic", "claude-3-haiku-20240307")).not.toBeNull();
    expect(pricing.get("google", "gemini-1.5-pro")).not.toBeNull();
    expect(pricing.get("google", "gemini-1.5-flash")).not.toBeNull();
  });
});
