/**
 * HikariInstrumentor: auto-instruments available LLM provider clients.
 *
 * Tries to patch OpenAI, Anthropic, and Google clients. Skips providers
 * that are not installed or have incompatible versions.
 */

import type { PricingModel } from "./pricing.js";
import * as openai from "./providers/openai.js";
import * as anthropic from "./providers/anthropic.js";
import * as google from "./providers/google.js";

/**
 * Manages auto-instrumentation of LLM provider clients.
 */
export class HikariInstrumentor {
  private patchedProviders: string[] = [];

  /**
   * Apply monkey-patches to all available provider clients.
   *
   * @param pricing - The pricing model to use for cost computation
   * @returns List of successfully patched provider names
   */
  instrument(pricing: PricingModel): string[] {
    this.patchedProviders = [];

    if (openai.patch(pricing)) {
      this.patchedProviders.push("openai");
    }

    if (anthropic.patch(pricing)) {
      this.patchedProviders.push("anthropic");
    }

    if (google.patch(pricing)) {
      this.patchedProviders.push("google");
    }

    return [...this.patchedProviders];
  }

  /**
   * Restore all patched provider clients to their original state.
   */
  uninstrument(): void {
    if (this.patchedProviders.includes("openai")) {
      openai.unpatch();
    }

    if (this.patchedProviders.includes("anthropic")) {
      anthropic.unpatch();
    }

    if (this.patchedProviders.includes("google")) {
      google.unpatch();
    }

    this.patchedProviders = [];
  }

  /**
   * Get the list of currently patched providers.
   *
   * @returns Array of patched provider names
   */
  getPatchedProviders(): string[] {
    return [...this.patchedProviders];
  }
}
