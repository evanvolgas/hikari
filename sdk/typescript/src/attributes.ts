/**
 * Hikari span attribute constants.
 *
 * All attributes are prefixed with `hikari.` to avoid collisions with
 * standard OpenTelemetry semantic conventions.
 */

/**
 * Explicit pipeline grouping identifier (optional).
 * Overrides the default trace ID-based pipeline grouping.
 */
export const PIPELINE_ID = "hikari.pipeline_id";

/**
 * Pipeline stage name (required).
 * Used to decompose pipeline cost by stage.
 */
export const STAGE = "hikari.stage";

/**
 * Model identifier (required).
 * Examples: `gpt-4`, `claude-3-haiku`, `gemini-1.5-pro`
 */
export const MODEL = "hikari.model";

/**
 * Provider name (required).
 * Examples: `openai`, `anthropic`, `google`
 */
export const PROVIDER = "hikari.provider";

/**
 * Input token count (required).
 */
export const TOKENS_INPUT = "hikari.tokens.input";

/**
 * Output token count (required).
 */
export const TOKENS_OUTPUT = "hikari.tokens.output";

/**
 * Computed input cost in USD (optional).
 * May be null if pricing model doesn't include this model.
 */
export const COST_INPUT = "hikari.cost.input";

/**
 * Computed output cost in USD (optional).
 * May be null if pricing model doesn't include this model.
 */
export const COST_OUTPUT = "hikari.cost.output";

/**
 * Computed total cost in USD (optional).
 * Sum of input and output costs. May be null if either component is null.
 */
export const COST_TOTAL = "hikari.cost.total";
