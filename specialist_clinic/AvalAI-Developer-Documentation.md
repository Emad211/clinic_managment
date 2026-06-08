# AvalAI Developer Documentation — Structured Reference (English)

> **Source:** Compiled from the AvalAI documentation at https://docs.avalai.ir/en/ (mirror: https://docs.avalai.org/en/).
>
> **How this was produced:** The docs site is a JavaScript‑rendered (Docsify) single‑page app, and the raw markdown sources are not served to non‑browser clients. This reference was therefore reconstructed from the publicly indexed content of every documentation page. Confirmed endpoints, base URLs, headers, and SDK patterns are accurate; **model catalogs, prices, and rate limits change frequently**, so always treat the live docs and the models endpoint (`/public/models`) as the authoritative source.
>
> **Last compiled:** June 2026

---

## Table of Contents

1. [What AvalAI Is](#1-what-avalai-is)
2. [Quick Start](#2-quick-start)
3. [Authentication & API Keys](#3-authentication--api-keys)
4. [Base URLs & Endpoint Map](#4-base-urls--endpoint-map)
5. [Client Libraries / SDKs](#5-client-libraries--sdks)
6. [API Reference: Chat Completions](#6-api-reference-chat-completions)
7. [API Reference: Messages (Anthropic‑compatible)](#7-api-reference-messages-anthropic-compatible)
8. [API Reference: Embeddings](#8-api-reference-embeddings)
9. [API Reference: Image Generation](#9-api-reference-image-generation)
10. [API Reference: Audio (TTS / STT)](#10-api-reference-audio-tts--stt)
11. [API Reference: Video Generation](#11-api-reference-video-generation)
12. [API Reference: OCR](#12-api-reference-ocr)
13. [API Reference: Moderation](#13-api-reference-moderation)
14. [API Reference: Search, Rerank, Files, Batch & Responses](#14-api-reference-search-rerank-files-batch--responses)
15. [API Reference: Models](#15-api-reference-models)
16. [Providers & Model Catalog](#16-providers--model-catalog)
17. [Guides](#17-guides)
18. [Worked Examples](#18-worked-examples)
19. [Pricing, Credits & Billing](#19-pricing-credits--billing)
20. [Rate Limits & Tiers](#20-rate-limits--tiers)
21. [Errors & Response Headers](#21-errors--response-headers)
22. [Usage Tracking & Cost Data](#22-usage-tracking--cost-data)
23. [Deprecations](#23-deprecations)
24. [Key Takeaways for Developers](#24-key-takeaways-for-developers)
25. [Source Pages](#25-source-pages)

---

## 1. What AvalAI Is

AvalAI is a **unified AI API platform / gateway** that exposes many model providers through a single, **OpenAI‑compatible** interface (and an **Anthropic‑compatible** interface for the Messages endpoint). Instead of integrating each provider separately, you point an OpenAI (or Anthropic) SDK at the AvalAI base URL and switch providers by changing the `model` field.

Key ideas:

- **One API, many providers.** OpenAI, Anthropic, Google, Meta, Mistral, xAI, DeepSeek, Cohere, Z.AI, MiniMax, Moonshot, Stability AI, Alibaba (Qwen), Black Forest Labs (FLUX), BytePlus (ByteDance), Cloudflare, ElevenLabs, Groq, and web‑search providers.
- **Drop‑in compatibility.** Works with the official OpenAI SDKs (Python, JS/TS) and the official Anthropic SDKs by only changing the base URL.
- **Persian/Iran‑focused service.** Billing is in Tomans, and the platform is designed to make global models accessible to developers in the region.
- **Capabilities beyond chat.** Embeddings, image generation, audio (TTS/STT), video generation (Sora/Veo), OCR, and moderation are all available through the same key.

---

## 2. Quick Start

The fastest path to a first request:

1. **Create an account** on the AvalAI dashboard.
2. **Generate an API key** in the dashboard. The key is shown **only once** — store it securely (e.g., an env file or secrets manager).
3. **Export environment variables** in your shell:

   ```bash
   export AVALAI_API_KEY="your-avalai-api-key"
   export OPENAI_BASE_URL="https://api.avalai.ir/v1"
   ```

4. **Install the OpenAI SDK** and make your first call:

   ```bash
   pip install openai
   ```

   ```python
   from openai import OpenAI

   client = OpenAI(
       api_key="your-avalai-api-key",          # or rely on AVALAI_API_KEY env var
       base_url="https://api.avalai.ir/v1",
   )

   response = client.chat.completions.create(
       model="gpt-4o",                          # any supported model id
       messages=[
           {"role": "user", "content": "Write a one-sentence bedtime story about a unicorn."}
       ],
   )

   print(response.choices[0].message.content)
   ```

   ```bash
   # cURL equivalent
   curl https://api.avalai.ir/v1/chat/completions \
     -H "Content-Type: application/json" \
     -H "Authorization: Bearer $AVALAI_API_KEY" \
     -d '{
       "model": "gpt-4o",
       "messages": [{"role": "user", "content": "Hello!"}]
     }'
   ```

---

## 3. Authentication & API Keys

- **Every endpoint requires authentication.** Pass your key as a Bearer token in the `Authorization` header:

  ```
  Authorization: Bearer $AVALAI_API_KEY
  ```

- Always send `Content-Type: application/json` on JSON requests.
- **Create keys in the dashboard.** A key is displayed once at creation — copy and store it immediately.
- **Keep keys server‑side.** Never embed a key in client‑side/browser code or commit it to source control.
- The one notable **public, unauthenticated** route is the public models list (see [§4](#4-base-urls--endpoint-map)).

---

## 4. Base URLs & Endpoint Map

| Purpose | Base URL |
|---|---|
| OpenAI‑compatible API | `https://api.avalai.ir/v1` |
| Anthropic‑compatible (Messages) | `https://api.avalai.ir` *(no `/v1` suffix — the SDK adds it)* |
| Public model list (no auth) | `https://api.avalai.ir/public/models` |
| User/account API (transactions, accurate cost) | `https://api.avalai.ir/user/v1` |

**Endpoint map (OpenAI‑compatible surface):**

| Capability | Method & Path |
|---|---|
| Chat completions | `POST /v1/chat/completions` |
| Messages (Anthropic schema) | `POST /v1/messages` |
| Embeddings | `POST /v1/embeddings` |
| Image generation | `POST /v1/images/generations` |
| Image edits | `POST /v1/images/edits` |
| Image variations | `POST /v1/images/variations` |
| Text‑to‑speech | `POST /v1/audio/speech` |
| Speech‑to‑text (transcription) | `POST /v1/audio/transcriptions` |
| Audio translation (to English) | `POST /v1/audio/translations` |
| Video generation | `POST /v1/videos` (+ retrieve by id) |
| OCR | `POST /v1/ocr` |
| Moderation | `POST /v1/moderations` |
| Rerank | `POST /v1/rerank` |
| Web search | `POST /v1/search` and `POST /v1/search/{search_tool_name}` |
| List models (authenticated) | `GET /v1/models` |
| List models (public) | `GET /public/models` |

> The API reference also documents **Files**, **Batch**, and **Responses** endpoints (OpenAI‑compatible) — see [§14](#14-api-reference-search-rerank-files-batch--responses).

---

## 5. Client Libraries / SDKs

AvalAI does not ship a proprietary SDK; you reuse the **official provider SDKs** by overriding the base URL.

**OpenAI SDK — Python**

```python
from openai import OpenAI
client = OpenAI(api_key="AVALAI_API_KEY", base_url="https://api.avalai.ir/v1")
```

**OpenAI SDK — JavaScript / TypeScript** (Node.js, Deno, Bun)

```javascript
import OpenAI from "openai";
const client = new OpenAI({
  apiKey: process.env.AVALAI_API_KEY,
  baseURL: "https://api.avalai.ir/v1",
});
```

**Anthropic SDK** (Python and JS/TS) — base URL is the host **without** `/v1`:

```javascript
import Anthropic from "@anthropic-ai/sdk";
const client = new Anthropic({
  apiKey: process.env.AVALAI_API_KEY,
  baseURL: "https://api.avalai.ir",   // SDK appends /v1/messages
});
```

**C#** — Microsoft's officially supported API client can be pointed at the AvalAI base URL.

Any other OpenAI‑compatible client/framework (LangChain, LlamaIndex, Vercel AI SDK, etc.) works the same way: set base URL + key.

---

## 6. API Reference: Chat Completions

The **core endpoint** of the platform: `POST /v1/chat/completions`.

**Common request parameters**

| Parameter | Description |
|---|---|
| `model` | Target model id (selects the provider/model, e.g. an OpenAI, Anthropic, Gemini, DeepSeek, Grok, or GLM model). |
| `messages` | Array of `{role, content}` objects. Roles: `system`, `user`, `assistant`, `tool`. |
| `temperature` | Sampling randomness (commonly 0–2). |
| `max_tokens` / `max_completion_tokens` | Upper bound on generated tokens. |
| `top_p`, `frequency_penalty`, `presence_penalty`, `stop`, `n`, `seed` | Standard OpenAI‑style controls. |
| `stream` | `true` to receive incremental Server‑Sent Events. |
| `tools` / `tool_choice` | Function/tool calling (JSON‑schema function definitions). |
| `response_format` | `{"type": "json_object"}` (JSON mode) or `{"type": "json_schema", ...}` (Structured Outputs). |
| `extra_body` | Pass **provider‑specific** native params (see [§16](#16-guides)). |

**Streaming**

```python
stream = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Count to 5"}],
    stream=True,
)
for chunk in stream:
    print(chunk.choices[0].delta.content or "", end="")
```

**Function / tool calling** — define functions with a JSON‑schema `parameters` object under `tools`; the model returns `tool_calls` you execute and feed back as a `tool` message.

**Vision (image input)** — supply images in the message content as an `image_url` (a URL or a base64 data URI) for vision‑capable models.

**Response shape** — includes `id`, `object`, `created`, `model`, `choices[]` (each with `message`, `finish_reason`), and `usage` (`prompt_tokens`, `completion_tokens`, `total_tokens`). AvalAI may also include an optional `estimated_cost` object.

---

## 7. API Reference: Messages (Anthropic‑compatible)

`POST /v1/messages` exposes the **Anthropic Messages API schema** so you can use the official Anthropic SDKs.

- **Base URL:** `https://api.avalai.ir` (the SDK appends `/v1/messages`).
- **Multi‑provider via Anthropic schema:** Any chat model that supports the chat‑completion endpoint can be called through the Anthropic SDK and the `/v1/messages` schema — not just Claude models.
- **Interleaved thinking & tool use:** Supported for reasoning‑capable models (e.g., MiniMax M2.x natively reasons between tool‑interaction rounds). Responses can contain `thinking`, `text`, and `tool_use` blocks handled separately.

```javascript
const message = await client.messages.create({
  model: "minimax-m2.1",
  max_tokens: 4096,
  messages: [{ role: "user", content: "Implement JWT auth in Node.js" }],
});
```

Anthropic **beta features** and provider‑specific behaviors are documented on the Anthropic model page.

---

## 8. API Reference: Embeddings

`POST /v1/embeddings` — convert text into vector representations for search, clustering, RAG, and ML.

```bash
curl https://api.avalai.ir/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AVALAI_API_KEY" \
  -d '{
    "model": "embed-v-4-0",
    "input": "Your text here"
  }'
```

- **`input`** accepts a string or an array of strings.
- **Models** include Cohere embedding models (e.g., an `embed-v-4-0` served via Azure AI infrastructure for higher rate limits and stability) and Cloudflare embedding models (e.g., a `cf.qwen3-embedding-*` family) for semantic search.
- Response returns embedding vectors plus token `usage`. Check the embeddings page / models endpoint for current dimensions and model ids.

---

## 9. API Reference: Image Generation

The Images API offers three operations:

| Operation | Endpoint | Purpose |
|---|---|---|
| Generations | `POST /v1/images/generations` | Create an image from a text prompt. |
| Edits | `POST /v1/images/edits` | Modify part of an image using a prompt + mask. |
| Variations | `POST /v1/images/variations` | Produce variations of an existing image. |

**Models (examples as documented):** GPT Image family (`gpt-image-1`, `gpt-image-1-mini`, and newer `gpt-image-1.5`), DALL·E (`dall-e-2`, `dall-e-3`), plus provider models such as Stability AI, FLUX (Black Forest Labs), and Gemini image models (the "Nano Banana" series). GPT Image 1 targets the highest quality; the Mini variant is cost‑efficient for high volume (availability can depend on account tier).

**Key parameters & features**

- Adjust **quality, size, output format/compression, and transparency**.
- For editing, upload the original image plus a **mask (PNG, same dimensions; transparent areas mark where to edit)**.
- Pass provider‑native params via `extra_body` — e.g., `seed`, `negative_prompt`, `mode`, and (for diffusion models) `cfg_scale` (~7.5), `steps` (~20–50), `safety_tolerance`.

**Best practices:** be detailed in prompts; use high‑contrast B/W masks; keep input images under ~4 MB; use supported formats (PNG, JPEG, WebP).

---

## 10. API Reference: Audio (TTS / STT)

The Audio API covers both directions:

| Capability | Endpoint |
|---|---|
| Text‑to‑Speech (TTS) | `POST /v1/audio/speech` |
| Speech‑to‑Text (transcription) | `POST /v1/audio/transcriptions` |
| Audio translation → English | `POST /v1/audio/translations` |

**Text‑to‑Speech**

```python
response = client.audio.speech.create(
    model="tts-1",
    voice="nova",
    input="Hello from AvalAI",
    response_format="mp3",
)
```

- **`model`** — e.g., `tts-1`, Gemini TTS (`gemini-2.5-flash-tts`, `gemini-2.5-pro-tts`), and ElevenLabs voices.
- **`voice`** — e.g., `alloy`, `nova`, `Kore` (Gemini voices differ).
- **`response_format`** — e.g., `mp3` (and other audio formats).

**Speech‑to‑Text**

- Models include **Whisper** and newer transcribe models (e.g., `gpt-4o-transcribe`).
- Response contains `task`, `language`, `duration`, `text`, and `segments` with timing/token detail.
- **Streaming:** when `stream=true` (for supporting models like `gpt-4o-transcribe`), the API emits SSE events — `transcript.text.delta` chunks followed by a final `transcript.text.done` with the full text.

---

## 11. API Reference: Video Generation

`POST /v1/videos` generates AI video using **OpenAI Sora** (`sora-2`, `sora-2-pro`) and **Google Veo** models. Generation is **asynchronous**: submit a job, then poll until it completes.

```python
from openai import OpenAI
client = OpenAI(api_key="your-avalai-api-key", base_url="https://api.avalai.ir/v1")

# 1) Create the job
video = client.videos.create(
    model="sora-2",
    prompt="A calico cat playing a piano on stage under dramatic spotlights",
    size="1280x720",
    seconds="4",            # e.g. "4" or "8"
)

# 2) Poll for completion
while video.status not in ("completed", "failed"):
    video = client.videos.retrieve(video.id)
```

- **Parameters:** `model`, `prompt`, `size` (e.g., `1280x720`), `seconds` (duration).
- **Status object fields:** `id`, `request_id`, `created_at`, `status`, `completed_at`, `model`, `progress`, `prompt`, `seconds`, and other metadata.
- ⚠️ **Do not blindly retry.** If a connection drops during/after submission, do **not** immediately fire a new generation request — you may be **double‑charged**. Check job status first.

A dedicated guide, *Generate Videos using Sora*, covers prompting and error handling/troubleshooting.

---

## 12. API Reference: OCR

`POST /v1/ocr` — extract text (and images) from PDFs and images using **Mistral OCR** (e.g., `mistral-ocr-latest`). Output is returned as structured **Markdown**.

**Document input types**

```json
{ "type": "document_url", "document_url": "https://example.com/document.pdf" }
```
```json
{ "type": "image_url", "image_url": "https://example.com/image.png" }
```

**cURL skeleton**

```bash
curl https://api.avalai.ir/v1/ocr \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AVALAI_API_KEY" \
  -d '{
    "model": "mistral-ocr-latest",
    "document": { "type": "document_url", "document_url": "https://example.com/doc.pdf" }
  }'
```

- **Structured output:** use `document_annotation_format` and `bbox_annotation_format` to receive results as a defined JSON structure instead of plain markdown (e.g., with bounding boxes).
- See the example *Process documents using Mistral OCR* for an end‑to‑end walkthrough.

---

## 13. API Reference: Moderation

`POST /v1/moderations` — classify potentially harmful text.

```python
client = OpenAI(api_key="AVALAI_API_KEY", base_url="https://api.avalai.ir/v1")
response = client.moderations.create(input="...")
```

- **Categories** (OpenAI‑style): `sexual`, `sexual/minors`, `hate`, `hate/threatening`, `harassment`, `harassment/threatening`, `self-harm`, `self-harm/intent`, `self-harm/instructions`, `violence`, `violence/graphic`.
- The response exposes a top‑level `flagged` boolean plus per‑category booleans/scores.
- ⚠️ **Status:** the docs indicate the moderation endpoint may be **under development / limited availability**, and model ids (e.g., `text-moderation-007`, `omni-moderation-*`) may change. Verify before relying on it in production.

> For provider‑native safety controls, see also the **Gemini Safety Settings** guide.

---

## 14. API Reference: Search, Rerank, Files, Batch & Responses

Beyond the core media/chat endpoints, the API reference documents several more:

**Web Search API** — programmatic access to web search from leading providers, returning structured results for use in your app or for grounding LLM answers.

- `POST /v1/search` — default web search.
- `POST /v1/search/{search_tool_name}` — target a specific search provider/tool.
- Results include **source links** for verification. Search can also be triggered automatically inside chat completions (web‑search‑augmented answers) for supported models.

**Rerank API** — `POST /v1/rerank`. Re‑orders a list of documents by relevance to a query, improving search/RAG quality over a large corpus. Powered by Cohere Rerank models (e.g., **Rerank v4**, in Pro and Fast variants).

```bash
curl https://api.avalai.ir/v1/rerank \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $AVALAI_API_KEY" \
  -d '{
    "model": "rerank-v4.0",
    "query": "What is the capital of France?",
    "documents": ["Paris is the capital of France.", "Berlin is in Germany."],
    "top_n": 2
  }'
```

**Files API** — upload and manage files (used by capabilities such as batch jobs and file‑based inputs), OpenAI‑compatible.

**Batch API** — submit large numbers of requests as an asynchronous batch for cost/throughput efficiency, then retrieve results when processing completes.

**Responses API** — OpenAI's newer stateful "Responses" interface is documented as part of the compatible surface for building agentic/multi‑turn flows.

> Exact request/response fields for Files, Batch, and Responses follow the corresponding OpenAI schemas; confirm specifics on the live API‑reference pages.

---

## 15. API Reference: Models

Two ways to enumerate available models and their metadata:

```bash
# Public (no authentication)
curl https://api.avalai.ir/public/models

# Authenticated (account-scoped)
curl https://api.avalai.ir/v1/models \
  -H "Authorization: Bearer $AVALAI_API_KEY"
```

Use these endpoints as the **single source of truth** for currently available `model` ids, since the catalog changes often. Per‑provider model pages under `/en/models/<provider>` describe capabilities, context windows, and provider‑specific notes.

---

## 16. Providers & Model Catalog

AvalAI aggregates many providers. The list below reflects providers and representative models **as documented at compile time** — confirm current ids via `/public/models`.

| Provider | Representative models (examples) |
|---|---|
| **OpenAI** | GPT‑5.x family (incl. Chat/Codex/Pro variants), GPT‑4o, GPT‑4.1, o3 / o4‑mini reasoning models, GPT Image, DALL·E, Whisper, TTS, **Sora‑2 / Sora‑2 Pro** |
| **Anthropic** | Claude Opus 4.x, Claude Sonnet 4.x, Claude Haiku 4.x, Claude 3.7 Sonnet |
| **Google** | Gemini 3.x (Pro / Flash / Flash‑Lite), Gemini 2.5 (Pro / Flash), Gemini image ("Nano Banana"), Gemini TTS, Gemma, **Veo** video |
| **DeepSeek** | DeepSeek‑V3.x (Chat), DeepSeek‑R1 (reasoning), DeepSeek Coder |
| **xAI** | Grok 4.x, Grok vision models |
| **Meta** | Llama family (served via Cloudflare and others) |
| **Mistral AI** | Mistral chat models, **Mistral OCR** |
| **Cohere** | Command models, **Rerank v4**, **Embed v4** (incl. Azure‑served variants) |
| **Z.AI** | GLM‑4.x family |
| **MiniMax** | MiniMax M2.x (interleaved thinking) |
| **Moonshot AI** | Kimi models |
| **Alibaba** | Qwen family |
| **Stability AI / Black Forest Labs** | Stable Diffusion, FLUX image models |
| **BytePlus (ByteDance)** | provider models |
| **Cloudflare** | Hosted open models (Llama, embeddings, image generation) |
| **ElevenLabs** | High‑quality TTS and STT |
| **Groq** | Fast inference for open models |
| **Web search** | Search‑augmented providers |

---

## 17. Guides

The documentation includes task‑oriented guides:

- **Image Generation** (`/guides/image-generation`) — choosing models, sizes/quality, edits and masks, prompt tips.
- **Generate Videos using Sora** (`/guides/generate-videos-using-sora`) — async workflow, polling, and error handling/troubleshooting.
- **Provider‑Specific Params** (`/guides/provider-specific-params`) — pass native, non‑OpenAI parameters through `extra_body` on the OpenAI‑compatible endpoint. Examples:
  - *Anthropic/Claude:* `enable_thinking: true`, `merge_reasoning_content_in_choices: true`, `chat_template_kwargs`, custom `parameters`.
  - *Image/diffusion:* `cfg_scale` (~7.5), `steps` (20–50), `seed`, `safety_tolerance` (~2). Avoid extreme values.
- **Reasoning** (`/guides/reasoning`) — using reasoning/thinking models and surfacing reasoning content.
- **Structured Outputs** (`/guides/structured-outputs`):
  - **Structured Outputs** (`response_format: { type: "json_schema", ... }`) — guarantees valid JSON that conforms to a supplied JSON Schema. Best for parsing into a UI or strict data extraction.
  - **JSON Mode** (`response_format: { type: "json_object" }`) — guarantees valid JSON but not schema conformance; relies on careful prompting. Use it for models that don't support `json_schema`.
  - **Function Calling vs. Structured Outputs:** function calling produces JSON to invoke *your* tools/functions; structured outputs shape the model's *direct answer* to the user. (Note: Claude uses XML‑style tool use under the hood; OpenAI uses JSON.)
- **Agents** (`/guides/agents`) — building tool‑using agentic workflows on top of the chat/messages endpoints.
- **Gemini Safety Settings** (`/guides/gemini-safety-settings`) — configuring Google's content‑safety thresholds.

---

## 18. Worked Examples

End‑to‑end recipes in the docs:

- **Processing PDFs in Chat Completions** — send PDF content into a chat model for Q&A/analysis.
- **Processing Audio in Chat Completions (Gemini)** — pass audio into multimodal chat models.
- **Generate Images with GPT Image Models** — practical `images.generations` usage.
- **Advanced Gemini Image Generation (Nano Banana series)** — high‑quality Gemini image workflows.
- **Process Documents using Mistral OCR** — full OCR pipeline via `/v1/ocr`.
- **ElevenLabs Text‑to‑Speech Example** — high‑fidelity TTS.
- **Anthropic SDK — Tool Use with Interleaved Thinking** — reasoning + tools across turns.
- **Web Search Capabilities** — grounding answers with live web search and source links.

---

## 19. Pricing, Credits & Billing

- **Per‑token pricing.** Prices are quoted **per 1,000,000 tokens** and are **aligned with each provider's base rates** — AvalAI advertises no hidden markup.
- **Free starter credit.** New users receive **25,000 Tomans** of free credit on registration.
- **Service tiers:**
  - **Default tier** — standard pricing; credit packages apply here.
  - **Flex tier** — ~**50% lower cost** for select OpenAI models; flex usage is billed against your **default account balance**, not from credit‑package allocations.
- **Cost visibility.** Responses can include an optional `estimated_cost` object for quick estimation; the **User API** (`https://api.avalai.ir/user/v1`) provides 100%‑accurate transaction and cost data.
- See the live **Pricing** page (`/en/pricing`) for the current per‑model table.

---

## 20. Rate Limits & Tiers

- Requests are **rate‑limited**; exceeding limits returns **HTTP 429 Too Many Requests**.
- **Account tiers** raise limits as your cumulative spend grows. **Tier 2** is the first paid tier for power users/teams, **unlocked once cumulative top‑ups reach ≈ $10 USD equivalent**; it has its own published rate‑limit table (`/en/rate-limits-tier2`).
- Some routes/models offer **higher rate limits** via alternative infrastructure (e.g., Cohere embeddings served through Azure).
- Implement **exponential backoff** on 429s and respect any rate‑limit headers.

---

## 21. Errors & Response Headers

- The API uses **conventional HTTP status codes**: `2xx` success, `4xx` client errors (auth, validation, rate limit), `5xx` server/provider errors.
- **`429`** signals rate limiting.
- Responses include tracking headers such as **`x-request-id`** — include it when contacting support about a specific request.
- Always send `Content-Type: application/json` for JSON bodies.

---

## 22. Usage Tracking & Cost Data

- **Dashboard analytics** break spend down by **model, provider, date, and hour**.
- **Inline estimates:** the optional `estimated_cost` field on responses gives a quick per‑call estimate.
- **Authoritative cost/transactions:** the **User API** at `https://api.avalai.ir/user/v1` exposes detailed, accurate billing data programmatically.

---

## 23. Deprecations

A **Deprecations** page (`/en/deprecations`) lists models that are retired or scheduled for removal and any recommended replacements. Check it periodically and pin to currently supported model ids (cross‑referenced with `/public/models`) to avoid breakage.

---

## 24. Key Takeaways for Developers

1. **Set two things and you're done:** base URL `https://api.avalai.ir/v1` + `Authorization: Bearer <key>`. Everything else mirrors the OpenAI API.
2. **Switch models by string.** Change `model` to move between OpenAI, Anthropic, Gemini, DeepSeek, Grok, GLM, etc.
3. **Two compatibility surfaces:** OpenAI (`/v1/...`) and Anthropic (`/v1/messages`, base URL without `/v1`).
4. **Reach native features with `extra_body`** (thinking/reasoning toggles, diffusion params, safety controls).
5. **The model list is dynamic** — read it from `/public/models`, not from any static list.
6. **Async jobs (video) must be polled**, and retries can double‑charge — check status first.
7. **Costs:** per‑1M‑token pricing at provider base rates; use `estimated_cost` and the User API for accurate accounting; mind default vs. flex tiers and rate‑limit tiers.
8. **Keep keys server‑side**; they're shown only once.

---

## 25. Source Pages

Primary documentation pages this reference was compiled from (English site; a Persian `/fa/` mirror exists):

- Home / Introduction — https://docs.avalai.ir/en/
- Quick Start — https://docs.avalai.ir/en/quickstart
- Libraries — https://docs.avalai.ir/en/libraries
- API Reference: Introduction — https://docs.avalai.ir/en/api-reference/introduction
- Chat Completions — https://docs.avalai.ir/en/api-reference/chat
- Messages (Anthropic) — https://docs.avalai.ir/en/api-reference/messages
- Embeddings — https://docs.avalai.ir/en/api-reference/embeddings
- Image Generation — https://docs.avalai.ir/en/api-reference/images
- Audio — https://docs.avalai.ir/en/api-reference/audio
- Video Generation — https://docs.avalai.ir/en/api-reference/videos
- OCR — https://docs.avalai.ir/en/api-reference/ocr
- Moderation — https://docs.avalai.ir/en/api-reference/moderation
- Search — https://docs.avalai.ir/en/api-reference/search
- Rerank — https://docs.avalai.ir/en/api-reference/rerank
- Models (index + per‑provider) — https://docs.avalai.ir/en/models/
- Pricing — https://docs.avalai.ir/en/pricing
- Rate Limits (Tier 2) — https://docs.avalai.ir/en/rate-limits-tier2
- Deprecations — https://docs.avalai.ir/en/deprecations
- Guides — image-generation, generate-videos-using-sora, provider-specific-params, reasoning, structured-outputs, agents, gemini-safety-settings (under https://docs.avalai.ir/en/guides/)
- Examples — processing_pdfs_in_chat_completion_api, processing_audio_in_chat_completion_api, generate_images_with_gpt_image, advanced_gemini_image_generation, processing_documents_with_mistral_ocr (under https://docs.avalai.ir/en/examples/)
- News / Changelog — https://docs.avalai.ir/en/news/

> ⚠️ **Verification note:** Specific model ids, prices, voices, and limits above are drawn from indexed documentation snapshots and **may be out of date**. Treat the live docs and `/public/models` as authoritative before building against any specific value.
