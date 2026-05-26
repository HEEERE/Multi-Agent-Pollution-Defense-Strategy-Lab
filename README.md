# Multi-Agent Cascading Pollution Detection & Defense Platform

A research and product platform for simulating, observing, recording, and replaying **Prompt Injection / RAG Context Poisoning / Tool Pollution Propagation** in multi-agent systems. Features a pluggable 3-level Monitor Pipeline with MiMo LLM detection for real-time alerting, blocking, and isolation.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, aiosqlite, Pydantic v2, httpx |
| Frontend | TypeScript 5.6, React 18, Vite 5, Tailwind CSS 3.4 |
| Visualization | @xyflow/react (ReactFlow), lucide-react |
| State | Zustand 5 |
| Database | SQLite (WAL mode) |
| LLM | MiMo (OpenAI-compatible API), with offline stub fallback |

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI entry point (~25 REST + 1 WebSocket)
│   │   ├── schemas.py               # Pydantic models & enums
│   │   ├── message_bus.py           # Central async event routing
│   │   ├── event_store.py           # SQLite persistence (WAL mode)
│   │   ├── websocket_manager.py     # WebSocket broadcast
│   │   ├── playbooks.py             # 6 attack/defense scenarios
│   │   ├── demo_topology.py         # Demo node wiring
│   │   ├── core/                    # Pydantic settings (.env)
│   │   ├── agents/base.py           # LLM-driven agent reasoning
│   │   ├── gateway/base.py          # Task submission gateway
│   │   ├── tools/base.py            # Tool event handling
│   │   ├── llm/                     # LLM abstraction (MiMo client + factory)
│   │   ├── detectors/               # Pluggable 3-level detection pipeline
│   │   │   ├── pipeline.py          # Chain-of-responsibility with short-circuit
│   │   │   ├── regex_detector.py    # Level 1: pattern matching
│   │   │   ├── rag_detector.py      # Level 2: RAG feature extraction
│   │   │   └── llm_detector.py      # Level 3: LLM intent detection
│   │   ├── monitoring/              # Security monitor nodes
│   │   ├── simulation/              # Round-based simulation engine
│   │   ├── experiments/             # Reproducible experiment runner + metrics
│   │   └── replay/                  # Cursor-based trace replay
│   ├── data/                        # SQLite database (gitignored)
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   └── src/
│       ├── pages/
│       │   ├── LiveMonitor.tsx      # Real-time topology + event console
│       │   ├── ExperimentStudio.tsx # Experiment runner + metrics dashboard
│       │   └── ReplayAnalyzer.tsx   # Step-through trace playback
│       ├── components/
│       │   ├── AgentNode.tsx        # Custom ReactFlow node
│       │   ├── EventConsole.tsx     # Real-time security event stream
│       │   ├── NodeDetailPanel.tsx  # Node detail popover
│       │   └── PlaybookPanel.tsx    # One-click playbook triggers
│       ├── store.ts                 # Zustand global state
│       ├── api.ts                   # Backend API client
│       └── types.ts                 # TypeScript type definitions
└── docs/
    └── platform-roadmap.md
```

## Key Capabilities

- **Multi-Agent Simulation Engine** -- Configurable topology, injection sources, turn-based LLM-driven conversations
- **Pluggable Monitor Pipeline** -- Level 1 regex (85%+ confidence) → Level 2 RAG feature matching → Level 3 LLM intent detection with configurable short-circuit
- **Event Store & Trace System** -- SQLite WAL persistence, trace_id-based causal chain tracking, full replay
- **Experiment System** -- Reproducible experiments with 10 automated metrics (propagation depth, TTD, FPR, intervention effectiveness, cascade depth, etc.)
- **Replay Engine** -- Cursor-based trace step-through with play/pause/seek/speed (0.1x–16x)
- **Visual Console** -- ReactFlow topology with real-time infection animation, event console, node detail panel
- **6 Built-in Playbooks** -- From explicit prompt injection to covert RAG poisoning and shared-memory contamination

## Quick Start

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

API docs: `http://127.0.0.1:8000/docs`

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

### Offline Demo Mode

Set `LLM_ENABLED=false` in `backend/.env` to run with deterministic stubs — no API key required. All detector pipelines, simulation, and replay work fully offline.

## MiMo LLM Configuration

```text
# backend/.env
MIMO_API_KEY=your-api-key
MIMO_BASE_URL=https://token-plan-cn.xiaomimimo.com/v1
MIMO_MODEL=MiMo-V2.5-Pro
LLM_ENABLED=true
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/events` | Query events by trace, severity, status |
| GET | `/api/traces` | List all trace summaries |
| GET | `/api/traces/{id}` | Full trace replay |
| DELETE | `/api/traces/{id}` | Delete a trace |
| GET | `/api/playbooks` | List playbook scenarios |
| POST | `/api/playbooks/{id}/run` | Run a playbook (streams via WebSocket) |
| POST | `/api/experiments` | Create and run an experiment |
| GET | `/api/experiments` | List all experiments |
| GET | `/api/experiments/{id}/metrics` | Get experiment metrics |
| POST | `/api/replay/{trace_id}/start` | Start replay session |
| POST | `/api/replay/{sid}/step` | Step forward/backward |
| POST | `/api/replay/{sid}/seek` | Seek to position |

WebSocket: `ws://127.0.0.1:8000/ws/events`

## License

MIT
