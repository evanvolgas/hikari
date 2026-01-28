"""
Hikari Python SDK Example

This example demonstrates how Hikari automatically instruments LLM provider
calls to track costs across a multi-stage pipeline.

Prerequisites:
    pip install hikari-python openai anthropic google-generativeai

Environment variables:
    OPENAI_API_KEY=sk-...
    ANTHROPIC_API_KEY=sk-ant-...
    GOOGLE_API_KEY=...
    HIKARI_ENDPOINT=http://localhost:8000  (optional, defaults to this)
"""

import asyncio
import os

import hikari

# Initialize Hikari - this auto-instruments all supported providers
hikari.configure(
    collector_endpoint=os.getenv("HIKARI_ENDPOINT", "http://localhost:8000"),
    # Optional: override default pricing for custom/fine-tuned models
    pricing={
        "openai": {
            "ft:gpt-4o-mini:my-org": {"input": 0.0004, "output": 0.0016}
        }
    },
)


def summarization_pipeline(document: str) -> dict:
    """
    A 3-stage document processing pipeline:
    1. Extract key points (GPT-4o)
    2. Generate summary (Claude)
    3. Create embedding for search (text-embedding-3-small)

    Hikari automatically:
    - Creates spans for each LLM call
    - Captures token counts and computes costs
    - Groups all calls under the same pipeline via trace propagation
    """
    from anthropic import Anthropic
    from openai import OpenAI

    openai_client = OpenAI()
    anthropic_client = Anthropic()

    # Stage 1: Extract key points
    # Hikari sets the stage name for cost attribution
    hikari.set_stage("extraction")

    extraction_response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "Extract 5 key points from this document."},
            {"role": "user", "content": document},
        ],
        max_tokens=500,
    )
    key_points = extraction_response.choices[0].message.content

    # Stage 2: Generate summary using Claude
    hikari.set_stage("summarization")

    summary_response = anthropic_client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=300,
        messages=[
            {
                "role": "user",
                "content": f"Write a concise summary based on these key points:\n{key_points}",
            }
        ],
    )
    summary = summary_response.content[0].text

    # Stage 3: Create embedding for semantic search
    hikari.set_stage("embedding")

    embedding_response = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=summary,
    )
    embedding = embedding_response.data[0].embedding

    return {
        "key_points": key_points,
        "summary": summary,
        "embedding": embedding[:5],  # Just first 5 dims for display
    }


async def async_pipeline_example():
    """
    Async pipeline example showing:
    - Custom pipeline ID for grouping related requests
    - Multiple concurrent LLM calls
    - Mixed provider usage
    """
    from anthropic import AsyncAnthropic
    from openai import AsyncOpenAI

    openai_client = AsyncOpenAI()
    anthropic_client = AsyncAnthropic()

    # Set a custom pipeline ID to group related requests
    # (otherwise Hikari uses the OpenTelemetry trace ID)
    hikari.set_pipeline_id("user-123-session-456")

    hikari.set_stage("parallel-generation")

    # Run multiple LLM calls concurrently - all tracked under same pipeline
    results = await asyncio.gather(
        openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Write a haiku about Python."}],
            max_tokens=50,
        ),
        anthropic_client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=50,
            messages=[{"role": "user", "content": "Write a haiku about TypeScript."}],
        ),
    )

    return {
        "openai_haiku": results[0].choices[0].message.content,
        "anthropic_haiku": results[1].content[0].text,
    }


def google_example():
    """
    Google Generative AI example.
    """
    import google.generativeai as genai

    hikari.set_stage("google-generation")

    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content("Explain quantum computing in one sentence.")

    return response.text


if __name__ == "__main__":
    print("=" * 60)
    print("Hikari Python SDK Examples")
    print("=" * 60)

    # Check for API keys
    has_openai = bool(os.getenv("OPENAI_API_KEY"))
    has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
    has_google = bool(os.getenv("GOOGLE_API_KEY"))

    if not any([has_openai, has_anthropic, has_google]):
        print("\nNo API keys found. Set at least one of:")
        print("  OPENAI_API_KEY")
        print("  ANTHROPIC_API_KEY")
        print("  GOOGLE_API_KEY")
        print("\nRunning in demo mode (no actual API calls)...\n")

        # Demo: show what the instrumentation captures
        print("When you run with real API keys, Hikari will:")
        print("  1. Auto-instrument OpenAI, Anthropic, and Google clients")
        print("  2. Create OpenTelemetry spans for each LLM call")
        print("  3. Capture token counts from provider responses")
        print("  4. Compute costs using the pricing model")
        print("  5. Export spans to the Hikari collector")
        print("\nSpan attributes captured:")
        print("  - hikari.pipeline_id: Groups related calls")
        print("  - hikari.stage: Cost attribution bucket")
        print("  - hikari.model: The model used")
        print("  - hikari.provider: openai/anthropic/google")
        print("  - hikari.tokens.input: Input token count")
        print("  - hikari.tokens.output: Output token count")
        print("  - hikari.cost.input: Input cost (USD)")
        print("  - hikari.cost.output: Output cost (USD)")
        print("  - hikari.cost.total: Total cost (USD)")
    else:
        # Run actual examples
        sample_doc = """
        Artificial intelligence has transformed how we build software.
        Large language models can now write code, answer questions, and
        generate creative content. However, the costs of running these
        models at scale can be significant, making cost observability
        crucial for production deployments.
        """

        if has_openai and has_anthropic:
            print("\n--- Summarization Pipeline (OpenAI + Anthropic) ---")
            try:
                result = summarization_pipeline(sample_doc)
                print(f"Key points extracted: {len(result['key_points'])} chars")
                print(f"Summary generated: {len(result['summary'])} chars")
                print(f"Embedding dims (first 5): {result['embedding']}")
            except Exception as e:
                print(f"Error: {e}")

            print("\n--- Async Pipeline (Concurrent calls) ---")
            try:
                result = asyncio.run(async_pipeline_example())
                print(f"OpenAI haiku: {result['openai_haiku']}")
                print(f"Anthropic haiku: {result['anthropic_haiku']}")
            except Exception as e:
                print(f"Error: {e}")

        if has_google:
            print("\n--- Google Generative AI ---")
            try:
                result = google_example()
                print(f"Response: {result}")
            except Exception as e:
                print(f"Error: {e}")

    # Always flush spans before exit
    hikari.shutdown()

    print("\n" + "=" * 60)
    print("Spans exported to Hikari collector.")
    print("Query pipeline costs at: GET /v1/pipelines/{pipeline_id}/cost")
    print("=" * 60)
