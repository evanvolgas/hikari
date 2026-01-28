/**
 * Context propagation for pipeline ID and stage using AsyncLocalStorage.
 *
 * Allows setting pipeline-level metadata that automatically propagates
 * through async call chains without explicit passing.
 */

import { AsyncLocalStorage } from "node:async_hooks";

export interface HikariContext {
  pipelineId?: string;
  stage?: string;
}

const storage = new AsyncLocalStorage<HikariContext>();

/**
 * Get the current pipeline ID from async context.
 *
 * @returns The pipeline ID, or undefined if not set
 */
export function getPipelineId(): string | undefined {
  return storage.getStore()?.pipelineId;
}

/**
 * Set the pipeline ID in the current async context.
 *
 * @param pipelineId - The pipeline identifier to set
 */
export function setPipelineId(pipelineId: string): void {
  const store = storage.getStore();
  if (store) {
    store.pipelineId = pipelineId;
  } else {
    storage.enterWith({ pipelineId });
  }
}

/**
 * Get the current stage name from async context.
 *
 * @returns The stage name, or undefined if not set
 */
export function getStage(): string | undefined {
  return storage.getStore()?.stage;
}

/**
 * Set the stage name in the current async context.
 *
 * @param stage - The stage name to set
 */
export function setStage(stage: string): void {
  const store = storage.getStore();
  if (store) {
    store.stage = stage;
  } else {
    storage.enterWith({ stage });
  }
}

/**
 * Run a function with a specific Hikari context.
 *
 * @param context - The context to set for the function execution
 * @param fn - The function to run with the given context
 * @returns The result of the function
 */
export function runWithContext<T>(
  context: HikariContext,
  fn: () => T
): T {
  return storage.run(context, fn);
}
