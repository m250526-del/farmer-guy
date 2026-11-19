# 🌾 KisaanDost (FarmAI)

**KisaanDost** ("Farmer's Friend") is an AI agricultural advisory assistant designed specifically for Pakistani farmers. A farmer speaks or types a query in Urdu, Roman Urdu, English, Punjabi, or Siraiki, and receives tailored agronomic guidance covering crop health, pest diagnosis, weather forecasts, mandi (market) prices, and irrigation schedules. Built with a FastAPI backend acting as the "agent brain" powered by Google Gemini, a React Native (Expo) mobile frontend, local agricultural RAG, and an n8n background automation layer, KisaanDost delivers actionable advice in the farmer's native language with both text and voice synthesis.

---

## 📌 Project Status

- **Stage 1 — Foundation**: ✅ Completed (FastAPI skeleton, Expo frontend blank scaffold, environment configurations, git setup).
- **Stage 2 — Key Manager & Gemini Core**: ✅ Completed (Rotating Gemini API key pools for CHAT, STT, and TTS with cooldowns, error classification, model fallback, secret scrubbing, diagnostic endpoints).
- **Stage 3 — Knowledge & RAG**: 🔄 **Next Up** (Document ingestion pipeline, vector store, agronomic knowledge retrieval tool).
- **Stages 4–9**: ⏳ Upcoming (Tools, Agent tool-calling loop, Voice STT/TTS, App screens, n8n workflows, Hardening).

See [AGENTS.md](./AGENTS.md) for the full 9-stage roadmap and progress log.

---

## 🛠 Tech Stack

| Layer | Technology | Details |
|---|---|---|
| **Frontend** | React Native + Expo (JavaScript) | Mobile app in `/frontend` with native fetch, responsive UI, voice recording. |
| **Backend Brain** | FastAPI + Uvicorn | Python 3.10+ async REST API in `/backend` with lifespan management. |
| **AI / LLM** | Google Gemini via `google-genai` SDK | Fixed models: `gemini-3.5-flash-lite` (Text/Reasoning, STT) & `gemini-3.8-flash-lite-tts` (TTS with voice `Aoede`). |
| **Resilience** | Domain Key Pools (`app/core/key_manager.py`) | Rotating keys across `CHAT`, `STT`, `TTS` with round-robin, rate-limit cooldowns, and automatic retry. |
| **Knowledge** | RAG (ChromaDB) | Local Pakistani agronomy guides and crop manuals (Stage 3). |
| **External Tools** | Open-Meteo & Mandi Rates | Real-time weather and market price scrapers/APIs (Stage 4). |
| **Automation** | n8n | Background workflows for SMS/WhatsApp alerts, reminders, and expert escalation (Stage 8). |

---

## 📁 Repository Structure

```
farmer_guy/
├── backend/                  # FastAPI backend application
│   ├── app/                  # Main application package (api, core, services, tools)
│   │   ├── api/              # API endpoints (health, gemini_status)
│   │   ├── core/             # Configuration, model lists, exceptions, key manager
│   │   └── services/         # Gemini client wrapper (generate_text)
│   ├── requirements.txt      # Python dependencies pinned to exact versions
│   └── .env.example          # Backend environment template with documentation
├── frontend/                 # React Native / Expo mobile application
│   ├── src/                  # Application source (config, services, screens)
│   │   ├── config.js         # API base URL configuration with missing-config guard
│   │   └── services/         # Frontend API integration (checkHealth)
│   ├── App.js                # Root application component (connectivity check screen)
│   ├── package.json          # Node dependencies (Expo SDK, React Native)
│   └── .env.example          # Frontend environment template
├── docs/                     # Project documentation & architecture references
│   └── ARCHITECTURE.md       # Technical architecture, request flow, and decisions
├── AGENTS.md                 # Single source of truth for build agents and developers
├── README.md                 # Project overview, quickstart, and status
└── .gitignore                # Git exclusions (secrets, venv, node_modules, audio)
```

---

## 🚀 Setup Instructions

### 1. Backend Setup

1. **Navigate to the backend directory**:
   ```bash
   cd backend
   ```
2. **Create and activate a virtual environment**:
   - On Windows (PowerShell):
     ```powershell
     python -m venv .venv
     .venv\Scripts\Activate.ps1
     ```
   - On macOS/Linux:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Configure environment variables**:
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Configure the necessary environment variables in `.env`:
     - `PROJECT_NAME`, `ENVIRONMENT` (`development` or `production`)
     - `GEMINI_API_KEY` (or domain keys `GEMINI_CHAT_KEY_1..3`, `GEMINI_STT_KEY_1..3`, `GEMINI_TTS_KEY_1..3`)
     - `GEMINI_MODEL`, `GEMINI_TTS_MODEL` (defaults provided in `.env.example`)
     - `GEMINI_REQUEST_TIMEOUT_SECONDS`, `KEY_COOLDOWN_SECONDS`
     - `OPEN_METEO_BASE_URL`, `N8N_WEBHOOK_BASE_URL`
   *(Never commit the `.env` file — it is ignored by git).*
5. **Run the backend server**:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```
6. **Verify health**:
   - Visit `http://localhost:8000/health` or `http://localhost:8000/gemini-status`.

### 2. Frontend Setup

1. **Navigate to the frontend directory**:
   ```bash
   cd frontend
   ```
2. **Install dependencies**:
   ```bash
   npm install
   ```
3. **Configure environment variables**:
   - Copy `.env.example` to `.env`:
     ```bash
     cp .env.example .env
     ```
   - Set `EXPO_PUBLIC_API_URL` to your computer's local network IP address (e.g., `http://192.168.1.100:8000`), so physical devices and emulators can reach the backend.
4. **Start the Expo development server**:
   ```bash
   npx expo start
   ```

---

## 🤖 For AI Assistants & LLMs

If you are an AI coding agent or LLM working on this repository:
1. **Read [AGENTS.md](./AGENTS.md) first** before proposing or applying any changes. It is the single source of truth for architecture invariants, rules, and current stage status.
2. **Read [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md)** for detailed request lifecycle diagrams, rotation algorithms, and API contracts.
3. **Standing Rules**:
   - **Never create, open, read, or print the contents of any real `.env` file.** Only reference `.env.example`.
   - **Never log, return, or commit secrets.** Refer to keys only by slot numbers (1, 2, 3).
   - **Additive changes only.** Do not refactor or break working code from earlier stages.
   - **Gemini SDK isolation.** All Gemini API calls must go through `app/services/gemini_client.py` and `app/core/key_manager.py`. Never call `google-genai` directly elsewhere.
