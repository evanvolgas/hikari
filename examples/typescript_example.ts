/**
 * Hikari TypeScript SDK Example
 *
 * This example demonstrates how Hikari automatically instruments LLM provider
 * calls to track costs across a multi-stage pipeline.
 *
 * Prerequisites:
 *     npm install hikari-js openai @anthropic-ai/sdk @google/generative-ai
 *
 * Environment variables:
 *     OPENAI_API_KEY=sk-...
 *     ANTHROPIC_API_KEY=sk-ant-...
 *     GOOGLE_API_KEY=...
 *     HIKARI_ENDPOINT=http://localhost:8000  (optional)
 *
 * Run:
 *     npx ts-node typescript_example.ts
 */

import * as hikari from "hikari-js";

// Initialize Hikari - this auto-instruments all supported providers
hikari.configure({
  endpoint: process.env.HIKARI_ENDPOINT ?? "http://localhost:8000",
  // Optional: override pricing for custom models
  pricingOverrides: {
    openai: {
      "ft:gpt-4o-mini:my-org": { input: 0.0004, output: 0.0016 },
    },
  },
});

/**
 * A 3-stage document processing pipeline:
 * 1. Extract key points (GPT-4o)
 * 2. Generate summary (Claude)
 * 3. Create embedding (text-embedding-3-small)
 *
 * Hikari automatically:
 * - Creates spans for each LLM call
 * - Captures token counts and computes costs
 * - Groups all calls under the same pipeline via trace propagation
 */
async function summarizationPipeline(document: string): Promise<{
  keyPoints: string;
  summary: string;
  embedding: number[];
}> {
  const OpenAI = (await import("openai")).default;
  const Anthropic = (await import("@anthropic-ai/sdk")).default;

  const openai = new OpenAI();
  const anthropic = new Anthropic();

  // Stage 1: Extract key points
  hikari.setStage("extraction");

  const extractionResponse = await openai.chat.completions.create({
    model: "gpt-4o",
    messages: [
      { role: "system", content: "Extract 5 key points from this document." },
      { role: "user", content: document },
    ],
    max_tokens: 500,
  });
  const keyPoints = extractionResponse.choices[0].message.content ?? "";

  // Stage 2: Generate summary using Claude
  hikari.setStage("summarization");

  const summaryResponse = await anthropic.messages.create({
    model: "claude-3-5-sonnet-20241022",
    max_tokens: 300,
    messages: [
      {
        role: "user",
        content: `Write a concise summary based on these key points:\n${keyPoints}`,
      },
    ],
  });
  const summary =
    summaryResponse.content[0].type === "text"
      ? summaryResponse.content[0].text
      : "";

  // Stage 3: Create embedding
  hikari.setStage("embedding");

  const embeddingResponse = await openai.embeddings.create({
    model: "text-embedding-3-small",
    input: summary,
  });
  const embedding = embeddingResponse.data[0].embedding;

  return {
    keyPoints,
    summary,
    embedding: embedding.slice(0, 5), // Just first 5 dims for display
  };
}

/**
 * Parallel pipeline example showing:
 * - Custom pipeline ID for grouping related requests
 * - Multiple concurrent LLM calls
 */
async function parallelPipelineExample(): Promise<{
  openaiHaiku: string;
  anthropicHaiku: string;
}> {
  const OpenAI = (await import("openai")).default;
  const Anthropic = (await import("@anthropic-ai/sdk")).default;

  const openai = new OpenAI();
  const anthropic = new Anthropic();

  // Set a custom pipeline ID to group related requests
  hikari.setPipelineId("user-123-session-456");
  hikari.setStage("parallel-generation");

  // Run multiple LLM calls concurrently - all tracked under same pipeline
  const [openaiResult, anthropicResult] = await Promise.all([
    openai.chat.completions.create({
      model: "gpt-4o-mini",
      messages: [{ role: "user", content: "Write a haiku about Python." }],
      max_tokens: 50,
    }),
    anthropic.messages.create({
      model: "claude-3-haiku-20240307",
      max_tokens: 50,
      messages: [{ role: "user", content: "Write a haiku about TypeScript." }],
    }),
  ]);

  return {
    openaiHaiku: openaiResult.choices[0].message.content ?? "",
    anthropicHaiku:
      anthropicResult.content[0].type === "text"
        ? anthropicResult.content[0].text
        : "",
  };
}

/**
 * Google Generative AI example
 */
async function googleExample(): Promise<string> {
  const { GoogleGenerativeAI } = await import("@google/generative-ai");

  const genai = new GoogleGenerativeAI(process.env.GOOGLE_API_KEY ?? "");
  const model = genai.getGenerativeModel({ model: "gemini-1.5-flash" });

  hikari.setStage("google-generation");

  const result = await model.generateContent(
    "Explain quantum computing in one sentence."
  );
  return result.response.text();
}

/**
 * Streaming example - Hikari captures final token counts after stream completes
 */
async function streamingExample(): Promise<string> {
  const OpenAI = (await import("openai")).default;
  const openai = new OpenAI();

  hikari.setStage("streaming");

  const stream = await openai.chat.completions.create({
    model: "gpt-4o-mini",
    messages: [{ role: "user", content: "Count from 1 to 5 slowly." }],
    stream: true,
    stream_options: { include_usage: true }, // Required for token counts in streams
  });

  let fullContent = "";
  for await (const chunk of stream) {
    const content = chunk.choices[0]?.delta?.content ?? "";
    fullContent += content;
    process.stdout.write(content);
  }
  console.log(); // newline

  return fullContent;
}

// Main execution
async function main(): Promise<void> {
  console.log("=".repeat(60));
  console.log("Hikari TypeScript SDK Examples");
  console.log("=".repeat(60));

  const hasOpenAI = Boolean(process.env.OPENAI_API_KEY);
  const hasAnthropic = Boolean(process.env.ANTHROPIC_API_KEY);
  const hasGoogle = Boolean(process.env.GOOGLE_API_KEY);

  if (!hasOpenAI && !hasAnthropic && !hasGoogle) {
    console.log("\nNo API keys found. Set at least one of:");
    console.log("  OPENAI_API_KEY");
    console.log("  ANTHROPIC_API_KEY");
    console.log("  GOOGLE_API_KEY");
    console.log("\nRunning in demo mode (no actual API calls)...\n");

    console.log("When you run with real API keys, Hikari will:");
    console.log("  1. Auto-instrument OpenAI, Anthropic, and Google clients");
    console.log("  2. Create OpenTelemetry spans for each LLM call");
    console.log("  3. Capture token counts from provider responses");
    console.log("  4. Compute costs using the pricing model");
    console.log("  5. Export spans to the Hikari collector");
    console.log("\nSpan attributes captured:");
    console.log("  - hikari.pipeline_id: Groups related calls");
    console.log("  - hikari.stage: Cost attribution bucket");
    console.log("  - hikari.model: The model used");
    console.log("  - hikari.provider: openai/anthropic/google");
    console.log("  - hikari.tokens.input: Input token count");
    console.log("  - hikari.tokens.output: Output token count");
    console.log("  - hikari.cost.input: Input cost (USD)");
    console.log("  - hikari.cost.output: Output cost (USD)");
    console.log("  - hikari.cost.total: Total cost (USD)");
  } else {
    const sampleDoc = `
      Artificial intelligence has transformed how we build software.
      Large language models can now write code, answer questions, and
      generate creative content. However, the costs of running these
      models at scale can be significant, making cost observability
      crucial for production deployments.
    `;

    if (hasOpenAI && hasAnthropic) {
      console.log("\n--- Summarization Pipeline (OpenAI + Anthropic) ---");
      try {
        const result = await summarizationPipeline(sampleDoc);
        console.log(`Key points extracted: ${result.keyPoints.length} chars`);
        console.log(`Summary generated: ${result.summary.length} chars`);
        console.log(`Embedding dims (first 5): ${result.embedding}`);
      } catch (e) {
        console.log(`Error: ${e}`);
      }

      console.log("\n--- Parallel Pipeline (Concurrent calls) ---");
      try {
        const result = await parallelPipelineExample();
        console.log(`OpenAI haiku: ${result.openaiHaiku}`);
        console.log(`Anthropic haiku: ${result.anthropicHaiku}`);
      } catch (e) {
        console.log(`Error: ${e}`);
      }
    }

    if (hasOpenAI) {
      console.log("\n--- Streaming Example ---");
      try {
        await streamingExample();
      } catch (e) {
        console.log(`Error: ${e}`);
      }
    }

    if (hasGoogle) {
      console.log("\n--- Google Generative AI ---");
      try {
        const result = await googleExample();
        console.log(`Response: ${result}`);
      } catch (e) {
        console.log(`Error: ${e}`);
      }
    }
  }

  // Always flush spans before exit
  await hikari.shutdown();

  console.log("\n" + "=".repeat(60));
  console.log("Spans exported to Hikari collector.");
  console.log("Query pipeline costs at: GET /v1/pipelines/{pipeline_id}/cost");
  console.log("=".repeat(60));
}

main().catch(console.error);
