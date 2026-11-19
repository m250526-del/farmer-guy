# AGENTS.md — KisaanDost (FarmAI) Build Guide

This file is the single source of truth for every AI agent and human developer working on this project. Read it in full before making any changes. Update the stage checklist and progress log after every completed stage.

---

> [!IMPORTANT]
> **Quick Context for New LLM Sessions**:
> - **Project**: KisaanDost (FarmAI) — AI agricultural advisory assistant for Pakistani farmers (Urdu, Roman Urdu, English, Punjabi, Siraiki).
> - **Architecture**: React Native (Expo) frontend + FastAPI backend brain + n8n background automation (never in live voice/chat path).
> - **Current Stage**: **Stage 3 — Knowledge & RAG** is in progress (Stage 1 Foundation and Stage 2 Key Manager & Gemini Core are completed).
> - **Active Models**: `gemini-3.5-flash-lite` (Text reasoning & STT) and `gemini-3.8-flash-lite-tts` (TTS with voice `Aoede`). Do not alter or add prefixes to these names.
> - **What to Read Next**: [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) for technical flow, key rotation, and API contract invariants.
> - **Standing Rules**: Never create or read real `.env` files; never commit or log secrets; make additive changes only; route all Gemini calls through `app/services/gemini_client.py` and `app/core/key_manager.py`.

---

## 1. Project Overview

**KisaanDost** ("Farmer's Friend") is an AI assistant for Pakistani farmers. A farmer speaks or types a question in Urdu, Roman Urdu, English, Punjabi, or Siraiki. The system responds with agronomic advice — crop health, weather, mandi prices, pest control, irrigation — in the farmer's language, as text and as synthesised voice.

### Architecture Split

```
┌─────────────────────┐        HTTPS / REST       ┌──────────────────────────┐
│   Expo Mobile App   │ ◄────────────────────────► │   FastAPI Agent Brain    │
│  (React Native JS)  │                             │  (Gemini tool-calling,   │
│    /frontend        │                             │   RAG, STT, TTS, tools)  │
└─────────────────────┘                             │       /backend           │
                                                    └───────────┬──────────────┘
                                                                │  background
                                                                │  webhook POST
                                                    ┌───────────▼──────────────┐
                                                    │        n8n               │
                                                    │  (automation layer,      │
                                                    │   scheduled alerts,      │
                                                    │   price watch,           │
                                                    │   expert escalation)     │
                                                    │        /n8n              │
                                                    └──────────────────────────┘
```

**Key architectural rule:** n8n is **never** in the live chat/voice path. It has too much latency for real-time interaction. FastAPI fires n8n webhooks in the background (fire-and-forget or async task) after responding to the farmer. n8n handles the slow, scheduled, or side-effect work:  
- Sending SMS/WhatsApp price alerts  
- Scheduled irrigation or spray reminders  
- Escalating complex cases to a human expert  
- Logging sessions for analytics  

---

## 2. Target Folder Structure (Finished Project)

```
farmer_guy/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI app, lifespan, routers
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── health.py            # GET /health
│   │   │   ├── analyze.py           # POST /analyze  (text query)
│   │   │   └── voice_analyze.py     # POST /voice-analyze (audio upload)
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   └── config.py            # pydantic-settings, get_settings()
│   │   ├── agent/
│   │   │   ├── __init__.py
│   │   │   ├── loop.py              # Gemini tool-calling loop
│   │   │   └── prompts.py           # System prompt templates
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── weather.py           # Open-Meteo tool
│   │   │   ├── mandi.py             # Mandi rates tool
│   │   │   └── image_validator.py   # Image validation tool
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── stt.py               # Gemini STT service
│   │   │   └── tts.py               # Gemini TTS service
│   │   ├── knowledge/
│   │   │   ├── __init__.py
│   │   │   └── rag.py               # RAG retrieval (ChromaDB or similar)
│   │   └── utils/
│   │       ├── __init__.py
│   │       └── helpers.py           # Shared utilities
│   ├── static/
│   │   └── audio/                   # TTS .wav output (gitignored)
│   ├── docs/                        # Crop knowledge documents (PDFs, txt)
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── config.js                # API_BASE_URL with guard
│   │   ├── services/
│   │   │   └── api.js               # checkHealth(), analyzeText(), voiceAnalyze()
│   │   ├── screens/                 # (added Stage 7)
│   │   ├── components/              # (added Stage 7)
│   │   └── hooks/                   # (added Stage 7)
│   ├── assets/
│   ├── App.js
│   ├── app.json
│   ├── package.json
│   └── .env.example
├── n8n/
│   └── workflows/                   # Exported n8n workflow JSON files
├── docs/                            # Project-level docs, diagrams, ADRs
├── .gitignore
├── README.md
└── AGENTS.md
```

---

## 3. Build Stages Checklist

- [x] **Stage 1 — Foundation** ✅  
  Root files, backend skeleton (FastAPI + health), frontend scaffold (Expo blank), `.env.example` files, virtual environment.

- [x] **Stage 2 — Key Manager & Gemini Core** ✅  
  Rotating API key manager, Gemini client wrapper, model selection logic.

- [ ] **Stage 3 — Knowledge & RAG** ← 🔄 IN PROGRESS  
  Document ingestion pipeline, vector store (ChromaDB), retrieval tool.

- [ ] **Stage 4 — Tools (Weather, Mandi, Image Validation)**  
  Open-Meteo weather tool, mandi price scraper/API tool, Gemini image validation tool.

- [ ] **Stage 5 — The Agent (Gemini Tool-Calling)**  
  Full tool-calling loop, `POST /analyze` endpoint, structured JSON response with all API contract keys.

- [ ] **Stage 6 — Voice (STT → Agent → TTS)**  
  `POST /voice-analyze`, Gemini STT transcription, TTS synthesis to `.wav`, `audio_url` in response.

- [ ] **Stage 7 — App Screens**  
  Chat screen, voice record screen, results display, activity feed, navigation.

- [ ] **Stage 8 — n8n Workflows & Agent Activity View**  
  n8n setup, webhook integration, price-watch workflow, reminder workflow, expert escalation workflow.

- [ ] **Stage 9 — Hardening**  
  Rate limiting, production CORS, auth, error budgets, load testing, secrets management.

---

## 4. Fixed Gemini Models

**Do not change these without an explicit instruction.** These are the models used throughout the project.

| Use Case | Models (in priority order) |
|----------|---------------------------|
| Text / Reasoning | `gemini-3.5-flash-lite` |
| STT | `gemini-3.5-flash-lite` |
| TTS | `gemini-3.8-flash-lite-tts` |

**TTS voice:** `Aoede` (always).

---

## 5. Key Rules for All Agents

1. **Never commit secrets.** No real API keys, passwords, or tokens in any file. Only `.env.example` with placeholder values.
2. **Never touch `.env` files.** `.env` files are created by the developer manually from `.env.example`. Agents must not create, overwrite, or read real `.env` files.
3. **Prefer additive changes.** Add new files and routes rather than rewriting existing ones. If a rewrite is necessary, explain why.
4. **Do not break existing features.** Each stage builds on the last. Run existing health checks mentally before adding new code.
5. **Do not commit or push** unless the user explicitly asks.
6. **After every stage:** update the checklist above (mark the stage done, mark the next one in-progress) and add an entry to the Progress Log below.
7. **All Gemini calls must go through `services/gemini_client.py` and `core/key_manager.py`.** Never import or call the `google-genai` SDK directly in any other file.

---

## 6. API Contract Invariants

The `/analyze` and `/voice-analyze` endpoints (added in Stages 5 and 6) **must always** return a JSON object with these top-level keys. Downstream code and the mobile app depend on their presence.

```jsonc
{
  "status": "ok" | "error",
  "farmer_response": "<string — NEVER null or empty; use safe Urdu fallback>",
  "tts_summary":     "<short string for TTS — never null>",
  "audio_url":       "<string | null — URL to .wav file, or null if no TTS>",
  "input_summary":   "<what the farmer asked, normalised>",
  "diagnosis":       "<structured crop/problem diagnosis or null>",
  "action_chain":    ["<step 1>", "<step 2>", "..."],
  "weather":         "<weather summary or null>",
  "irrigation_advice": "<string or null>",
  "cost_summary":    "<estimated cost string or null>",
  "contradictions":  "<any conflicting advice flagged or null>",
  "recovery":        "<recovery plan or null>",
  "gemini_status":   "ok" | "fallback" | "error",
  "rag_status":      "ok" | "skipped" | "error"
}
```

**Invariants:**
- `farmer_response` must **never** be `null` or empty. If Gemini fails, use the safe Urdu fallback: `"معذرت، ابھی جواب دینا ممکن نہیں۔ براہ کرم دوبارہ کوشش کریں۔"`
- Gemini answer headings must **never** contain markdown `**` bold asterisks in the final farmer-facing text.
- All keys listed above must exist in every response, even if their value is `null`.

---

## 7. Functions and Modules

This section is updated after each stage as new code is added.

### Stage 1 — Foundation

| File | Symbol | Description |
|------|--------|-------------|
| `backend/app/main.py` | `app` | FastAPI application instance |
| `backend/app/main.py` | `lifespan()` | Async lifespan context manager (startup/shutdown) |
| `backend/app/core/config.py` | `Settings` | Pydantic-settings class; reads from `.env` |
| `backend/app/core/config.py` | `get_settings()` | Cached settings getter (`@lru_cache`) |
| `backend/app/api/health.py` | `health_check()` | `GET /health` → `{"status":"ok","project":"FarmAI","environment":"..."}` |
| `frontend/src/config.js` | `API_BASE_URL` | Exported URL string; guarded against missing/placeholder value |
| `frontend/src/services/api.js` | `checkHealth()` | `GET /health` with 10 s AbortController timeout; returns parsed JSON |

### Stage 2 — Key Manager & Gemini Core

| File | Symbol | Description |
|------|--------|-------------|
| `backend/app/core/models.py` | `TEXT_MODELS`, `STT_MODELS`, `TTS_MODELS`, `TTS_VOICE` | Fixed model-name constants (never alter) |
| `backend/app/core/models.py` | `get_text_models()` | Returns TEXT_MODELS with optional GEMINI_MODEL override prepended |
| `backend/app/core/models.py` | `get_tts_models()` | Returns TTS_MODELS with optional GEMINI_TTS_MODEL override prepended |
| `backend/app/core/models.py` | `get_stt_models()` | Returns STT_MODELS (no override yet) |
| `backend/app/core/exceptions.py` | `NoKeysConfiguredError` | Raised when a domain's key pool is empty |
| `backend/app/core/exceptions.py` | `AllKeysExhaustedError` | Raised when every key in a pool has been tried and failed |
| `backend/app/core/exceptions.py` | `GeminiUnavailableError` | Raised when every model in the list fails |
| `backend/app/core/exceptions.py` | `EmptyGeminiResponseError` | Raised when Gemini returns a blocked/empty response |
| `backend/app/core/key_manager.py` | `init_pools()` | Builds CHAT/STT/TTS key pools from settings; call once at lifespan startup |
| `backend/app/core/key_manager.py` | `run_with_key_rotation()` | Runs an async operation with automatic key rotation, cooldowns, and retry |
| `backend/app/core/key_manager.py` | `classify_exception()` | Maps SDK/network exceptions to rotation strategy categories |
| `backend/app/core/key_manager.py` | `scrub_secrets()` | Replaces key values with `[REDACTED]` before logging |
| `backend/app/services/gemini_client.py` | `generate_text()` | Generic async text generation with model fallback; returns `GeminiTextResult` |
| `backend/app/api/gemini_status.py` | `GET /gemini-status` | Pool sizes + model lists; never exposes key values |
| `backend/app/api/gemini_status.py` | `GET /gemini-test` | Live key test for a domain (dev only; 404 in production) |
| `backend/app/api/gemini_status.py` | `GET /gemini-models-check` | Tests each text model individually (dev only; 404 in production) |

---

## 8. Progress Log

| Stage | Date | Notes |
|-------|------|-------|
| Stage 1 | 2026-11-19 | Foundation scaffolded: root files, FastAPI skeleton with health route, Expo blank app with health-check screen, virtual environment created and dependencies installed. |
| Stage 2 | 2026-11-19 | Key manager (CHAT/STT/TTS pools, round-robin rotation, per-key cooldown, permanent bad-key marking), Gemini client (model fallback, timeout, image support stub, empty-response guard), three /gemini-status/test/models-check endpoints, google-genai==3.6.1 installed. |
| Stage 2 Follow-up | 2026-11-19 | Model lists changed to gemini-3.5-flash-lite (text, STT) and gemini-3.8-flash-lite-tts (TTS). |
| Documentation | 2026-11-19 | Added README.md, docs/ARCHITECTURE.md, and new LLM quick context block in AGENTS.md. |

