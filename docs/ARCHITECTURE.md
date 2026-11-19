# KisaanDost (FarmAI) — Architecture & Technical Specifications

This document details the internal design, request flow, resilience patterns, and configuration specifications of the KisaanDost backend.

---

## 1. System Overview & Architecture Split

KisaanDost follows a strict 3-tier decoupling to balance real-time conversational low-latency with robust background automation:

```
┌─────────────────────────────────┐
│     Expo Mobile App             │
│   (React Native JS Frontend)    │
└────────────────┬────────────────┘
                 │
                 │ HTTPS (REST API)
                 ▼
┌─────────────────────────────────┐
│     FastAPI Brain               │
│  - Rotating Key Pools           │
│  - Gemini Client & Tool Loop    │
│  - Local Agronomic RAG          │
│  - Weather & Mandi Tools        │
└────────────────┬────────────────┘
                 │
                 │ Async Webhook POST (Background only)
                 ▼
┌─────────────────────────────────┐
│     n8n Automation Engine       │
│  - Scheduled Weather / Mandi    │
│  - SMS / WhatsApp Alerts        │
│  - Expert Human Escalation      │
└─────────────────────────────────┘
```

> [!IMPORTANT]
> **Latency Rule:** n8n is **never** placed in the live user request/response path. All farmer questions are answered directly and immediately by the FastAPI brain. FastAPI triggers n8n webhooks asynchronously in the background for side effects and scheduled workflows.

---

## 2. Request Lifecycle & Brain Flow

1. **Inbound Request**: Farmer sends voice or text via the Expo mobile client to `/analyze` or `/voice-analyze`.
2. **Audio / Text Ingestion**: If voice, audio is transcribed using Gemini STT (`services/stt.py` via `gemini-3.5-flash-lite`).
3. **Agent Brain & Tool Loop**:
   - The agent evaluates the query against available tools (RAG retrieval, Open-Meteo weather, Mandi rates, Image validation).
   - Relevant agronomic documents are retrieved from the local vector database.
   - Real-time weather and market prices are queried when applicable.
4. **Synthesis & Reasoning**:
   - Gemini (`gemini-3.5-flash-lite`) reasons over farmer input and tool outputs to formulate diagnosis, action chains, and irrigation advice in the farmer's language.
   - Output text is cleaned to ensure no markdown bold asterisks appear in headings.
5. **TTS Synthesis**: If audio output is requested, Gemini TTS (`gemini-3.8-flash-lite-tts`, voice `Aoede`) synthesizes a concise voice response.
6. **Delivery & Background Trigger**:
   - The response is returned to the farmer matching the invariant JSON schema.
   - Background tasks trigger n8n webhooks for price tracking or expert escalation if high-risk anomalies are identified.

---

## 3. Key Manager & Pool Resilience (`app/core/key_manager.py`)

To handle Gemini API quota limits, rate limits (HTTP 429), and intermittent network issues without impacting the end user, KisaanDost implements a domain-separated, rotating key pool.

### Domains
- `CHAT`: For conversational reasoning and text generation.
- `STT`: For speech-to-text audio transcription.
- `TTS`: For text-to-speech audio synthesis.

### Pool Initialization & Storage
- Loaded lazily at startup via `init_pools()` in the FastAPI lifespan handler (`app/main.py`).
- Reads `GEMINI_<DOMAIN>_KEY_1..3` from environment variables.
- If a domain lacks dedicated keys, it gracefully falls back to `GEMINI_API_KEY`.
- If no keys exist at all, the app starts with a warning and raises `NoKeysConfiguredError` only when that domain is called.

### Concurrency & Round-Robin Rotation
- An `asyncio.Lock` protects the cursor and slot states against race conditions during concurrent async requests.
- Requests cycle round-robin through active keys to distribute quota usage evenly.

### Exception Classification & Strategies (`classify_exception`)

The key manager inspects exact SDK exception attributes (`exc.code`, `exc.status`, `exc.message` from `google.genai.errors.APIError` and network exception types):

| Error Category | Indicators | Key Manager Strategy |
|---|---|---|
| `quota_or_rate_limit` | HTTP `429` or status `RESOURCE_EXHAUSTED` | Key placed on cooldown for `KEY_COOLDOWN_SECONDS` (default: 60s); rotates immediately to next key. |
| `invalid_api_key` | HTTP `401`, `403`, or `400` mentioning invalid key / unauthenticated | Key marked permanently `bad = True` for process lifetime; rotates immediately to next key. |
| `transient` | HTTP `500`, `502`, `503`, `504`, timeouts, connection drops | Retries the **same key once** after a 0.5s pause; if retry fails, re-classifies the second exception (applying cooldown or marking bad if applicable) before rotating to next key. |
| `model_not_found` | HTTP `404` or status `NOT_FOUND` | **Not a key error.** Re-raised immediately to let caller attempt model fallback. |
| `invalid_request` | HTTP `400` malformed request/arguments | **Not a key error.** Re-raised immediately without rotating keys. |
| `unknown` | Unrecognized error | Re-raised immediately without rotating keys. |

### Cooldown Evacuation
If all keys in a pool are currently in cooldown, rather than failing immediately, the key manager selects the key whose cooldown expires soonest.

### Secret Scrubbing (`scrub_secrets`)
Before any exception or debug log is emitted, all configured API keys are scrubbed from text and replaced with `[REDACTED]`. Logs refer only to key slot indices (`slot 1`, `slot 2`, `slot 3`).

---

## 4. Gemini Client (`app/services/gemini_client.py`)

All interactions with the official Google Gen AI SDK (`google-genai`) are centralized in `app/services/gemini_client.py`.

### Capabilities:
- **Async Execution**: Employs `client.aio.models.generate_content` so the server never blocks the Python async event loop.
- **Model Fallback**: Iterates through the configured model list in priority order. If a model fails with `model_not_found`, it moves to the next model in the list.
- **Timeouts**: Enforces timeouts at the SDK level via `HttpOptions(timeout=timeout_ms)` in milliseconds (converting `GEMINI_REQUEST_TIMEOUT_SECONDS * 1000`, extending by +15,000ms if an image is attached).
- **Image Support**: Prepares multimodal inputs (`ImageInput` with bytes and MIME type) for crop pest/disease image diagnosis.
- **Empty Response Guard**: Checks response text and candidate safety finish reasons, raising `EmptyGeminiResponseError` if the model produced no usable text.
- **Return Type**: Yields a structured `GeminiTextResult` containing `text`, `model_used`, `key_slot`, and `latency_ms`.

---

## 5. Diagnostic Endpoints (`app/api/gemini_status.py`)

| Endpoint | Environment | Description |
|---|---|---|
| `GET /gemini-status` | All (`dev` & `prod`) | Returns counts of configured keys per domain and effective model lists. Never returns secrets or partial keys. |
| `GET /gemini-test?domain=CHAT` | Development only | Sends `"Reply with exactly: OK"` through the chosen domain's pool. Verifies live key validity. On failure returns `attempts` detailing `exception_type` and scrubbed `message`. Returns 404 in production. |
| `GET /gemini-models-check?domain=CHAT` | Development only | Tests each model in the list individually without fallback. Returns per-model health with `exception_type` and scrubbed `message`. Returns 404 in production. |

---

## 6. Environment Variables Reference

All variables are optional with safe defaults to allow local development and scaffolding without secrets:

| Variable Name | Default | Purpose |
|---|---|---|
| `PROJECT_NAME` | `FarmAI` | Application display name. |
| `ENVIRONMENT` | `development` | Deployment environment (`development` or `production`). Production disables test endpoints. |
| `GEMINI_API_KEY` | `None` | Default fallback API key if domain-specific keys are not provided. |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Primary text and reasoning model override. |
| `GEMINI_TTS_MODEL` | `gemini-3.8-flash-lite-tts` | Primary TTS model override. |
| `GEMINI_CHAT_KEY_1..3` | `None` | Rotating API key slots 1 to 3 for chat / reasoning. |
| `GEMINI_STT_KEY_1..3` | `None` | Rotating API key slots 1 to 3 for speech-to-text. |
| `GEMINI_TTS_KEY_1..3` | `None` | Rotating API key slots 1 to 3 for text-to-speech. |
| `OPEN_METEO_BASE_URL` | `https://api.open-meteo.com/v1/forecast` | Base URL for Open-Meteo weather forecast queries. |
| `N8N_WEBHOOK_BASE_URL` | `None` | Base URL of the n8n automation instance for webhook triggers. |
| `GEMINI_REQUEST_TIMEOUT_SECONDS` | `30` | Timeout in seconds for individual Gemini API calls. |
| `KEY_COOLDOWN_SECONDS` | `60` | Duration in seconds a rate-limited key is paused before retry. |
| `EXPO_PUBLIC_API_URL` (Frontend) | `None` | Backend API base URL consumed by the Expo mobile app. |

---

## 7. Known Architectural Decisions & Constraints

1. **Fixed Model Names**: Model strings are pinned to `gemini-3.5-flash-lite` (text/STT) and `gemini-3.8-flash-lite-tts` (TTS). AI agents must never "correct" or prepend `models/` to these strings.
2. **Production Endpoint Masking**: Diagnostic test endpoints `/gemini-test` and `/gemini-models-check` return HTTP 404 when `ENVIRONMENT="production"` to prevent quota abuse and surface area leakage.
3. **Additive Development**: New stages build upon earlier stages without rewrites. All modules import through `core/config.py` and `core/key_manager.py`.
4. **Secret Isolation**: Real `.env` files must never be checked into git, printed to logs, or accessed by AI agents.
