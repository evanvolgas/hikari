/**
 * Pluggable pricing model for per-token cost computation.
 *
 * Loads bundled default pricing and allows runtime overrides.
 * Lookup key format: `{provider}/{model}` (e.g., `openai/gpt-4o`)
 */

/**
 * Default pricing data bundled with the SDK.
 * Costs are in USD per token.
 */
const DEFAULT_PRICING: Record<string, { inputCostPerToken: number; outputCostPerToken: number }> = {
  "openai/gpt-4o": {
    inputCostPerToken: 0.0000025,
    outputCostPerToken: 0.00001,
  },
  "openai/gpt-4o-mini": {
    inputCostPerToken: 0.00000015,
    outputCostPerToken: 0.0000006,
  },
  "anthropic/claude-3-5-sonnet-20241022": {
    inputCostPerToken: 0.000003,
    outputCostPerToken: 0.000015,
  },
  "anthropic/claude-3-haiku-20240307": {
    inputCostPerToken: 0.00000025,
    outputCostPerToken: 0.00000125,
  },
  "google/gemini-1.5-pro": {
    inputCostPerToken: 0.00000125,
    outputCostPerToken: 0.000005,
  },
  "google/gemini-1.5-flash": {
    inputCostPerToken: 0.000000075,
    outputCostPerToken: 0.0000003,
  },
};

export interface ModelPricing {
  inputCostPerToken: number;
  outputCostPerToken: number;
}

export interface CostResult {
  inputCost: number | null;
  outputCost: number | null;
  totalCost: number | null;
}

/**
 * Manages per-model token pricing and cost computation.
 */
export class PricingModel {
  private readonly table: Map<string, ModelPricing>;

  /**
   * Create a new pricing model with optional overrides.
   *
   * @param overrides - Optional pricing overrides keyed by `{provider}/{model}`
   */
  constructor(overrides?: Record<string, ModelPricing>) {
    this.table = new Map();

    // Load bundled defaults
    for (const [key, value] of Object.entries(DEFAULT_PRICING)) {
      this.table.set(key, value);
    }

    // Apply user overrides
    if (overrides) {
      for (const [key, value] of Object.entries(overrides)) {
        this.table.set(key, value);
      }
    }
  }

  /**
   * Get pricing for a specific provider and model.
   *
   * @param provider - The provider name (e.g., `openai`)
   * @param model - The model identifier (e.g., `gpt-4o`)
   * @returns The pricing, or null if the model is not in the pricing table
   */
  get(provider: string, model: string): ModelPricing | null {
    const key = `${provider}/${model}`;
    return this.table.get(key) ?? null;
  }

  /**
   * Compute costs for a given provider, model, and token counts.
   *
   * @param provider - The provider name
   * @param model - The model identifier
   * @param inputTokens - Number of input tokens (or null if unknown)
   * @param outputTokens - Number of output tokens (or null if unknown)
   * @returns Object with inputCost, outputCost, and totalCost (any may be null)
   */
  computeCost(
    provider: string,
    model: string,
    inputTokens: number | null,
    outputTokens: number | null
  ): CostResult {
    const pricing = this.get(provider, model);

    let inputCost: number | null = null;
    let outputCost: number | null = null;
    let totalCost: number | null = null;

    if (pricing !== null && inputTokens !== null) {
      inputCost = pricing.inputCostPerToken * inputTokens;
    }

    if (pricing !== null && outputTokens !== null) {
      outputCost = pricing.outputCostPerToken * outputTokens;
    }

    if (inputCost !== null && outputCost !== null) {
      totalCost = inputCost + outputCost;
    }

    return { inputCost, outputCost, totalCost };
  }

  /**
   * Update pricing for a specific model at runtime.
   *
   * @param modelKey - The model key in format `{provider}/{model}`
   * @param inputCostPerToken - Cost per input token in USD
   * @param outputCostPerToken - Cost per output token in USD
   */
  update(modelKey: string, inputCostPerToken: number, outputCostPerToken: number): void {
    this.table.set(modelKey, { inputCostPerToken, outputCostPerToken });
  }
}
