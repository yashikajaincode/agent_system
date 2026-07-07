# Autonomous Document Agent

A FastAPI service that takes a natural language business request, plans its own tasks, executes them, and returns a polished `.docx` document (proposal, meeting 
minutes, project plan, business report, technical design, or SOP) — inferring the document type and, when the request is ambiguous, explicitly stating the 
assumptions it made rather than guessing silently or refusing.

Built with plain Python (no LangChain/LangGraph/CrewAI) so every step is fully
inspectable.

## Architecture

```
POST /agent
  │
  ├─ Planner       single LLM call (JSON mode) → classifies doc type, states
  │                assumptions for missing info, emits a task list
  │
  ├─ Executor      runs tasks in dependency order (topological sort)
  │                - "generate" tasks → LLM call for that section
  │                - "tool" tasks     → LLM decides which tool to call via
  │                  native Groq function-calling, then it's dispatched
  │                - every task: try → 1 retry with self-correction reprompt →
  │                  safe fallback content on second failure (never crashes)
  │
  ├─ Validator     checks required sections are present per doc type, fills
  │                any gaps with a placeholder rather than failing
  │
  └─ DocxBuilder   renders the final .docx: title page, styled headings,
                   "Assumptions Made" section, all generated content
```

**The mandatory engineering improvement: Tool Calling.** The Executor hands the
LLM the real tool schemas (`get_current_date`, `estimate_cost`, `lookup_template`)
via Groq's native function-calling API, and the model itself decides which tool
to call and with what arguments — the Planner only leaves a non-binding hint.

## Project structure

```
app/
  main.py                 FastAPI app: /agent, /health, /download/{file}, /
  static/index.html        Basic web UI (form + live execution log + docx download)
  models/schemas.py        Pydantic models (Task, Plan, TaskLog, AgentResponse...)
  agent/planner.py         Planning LLM call
  agent/executor.py        Task execution, retry/fallback, logging
  agent/validator.py       Pre-doc-gen section coverage check
  tools/tool_manager.py    3 mock tools + Groq tool schemas + dispatch
  documents/docx_builder.py  python-docx rendering
  core/config.py           Settings (.env)
  core/llm_client.py       Thin Groq SDK wrapper
tests/
  test_planner.py          Planner output validates against schema (mocked LLM)
  test_docx_builder.py      Builder produces a non-empty valid .docx
output/                    Generated documents land here (gitignored)
```

## Setup

**Requirements:** Python 3.11+ and a free [Groq API key](https://console.groq.com/keys).

```bash
# 1. Move into the project folder
cd agent_system

# 2. (Recommended) create a virtual environment
python -m venv venv

# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy the env template and add your real Groq API key
# Windows (PowerShell):
cp .env.example .env
# macOS/Linux:
cp .env.example .env
```

Open `.env` in any text editor and replace the placeholder with your real key:
```
GROQ_API_KEY=your_actual_key_here
```

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

- **Web UI:** open http://127.0.0.1:8000/ in your browser — enter a request, run
  the agent, see the live plan/execution log, and download the generated `.docx`.
- **Interactive API docs:** http://127.0.0.1:8000/docs
- **Health check:** http://127.0.0.1:8000/health

## API usage

### Standard request

```bash
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"request": "Write a project plan for migrating our internal analytics tool to microservices, targeting Q4 completion with a team of 4 engineers"}'
```

### Ambiguous request (triggers the "Assumptions Made" section)

```bash
curl -X POST http://localhost:8000/agent \
  -H "Content-Type: application/json" \
  -d '{"request": "Draft something for the client about the new thing we discussed"}'
```

Both return JSON with:
- `plan` — the full agent-generated task list (doc type, assumptions, tasks) — the
  visible proof of autonomous planning
- `execution_log` — per-task `{task_id, status, duration_ms, retry_count}`
- `document_path` — path to the generated `.docx` in `output/`

**Windows PowerShell note:** curl's quoting can be finicky in PowerShell. If the
command above errors, use this instead:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/agent" -Method Post -ContentType "application/json" -Body '{"request": "Write a project plan for migrating our internal analytics tool to microservices, targeting Q4 completion with a team of 4 engineers"}'
```

## Tests

Exactly two unit tests, as scoped — planner schema validation and docx builder
output, both fully mocked (no API key required to run them):

```bash
pytest tests/ -v
```

## Notes on design tradeoffs

- **No general DAG scheduler** — dependency resolution is a simple topological
  (Kahn's algorithm) sort, sufficient for the shallow task graphs this agent
  produces, not built to handle arbitrary workflow complexity.
- **Retry is fixed at 1 attempt, no exponential backoff** — per spec, this keeps
  latency predictable for a demo; a production system would likely want backoff
  and a circuit breaker for sustained LLM outages.
- **No conversation memory / RAG / multi-agent** — explicitly out of scope; each
  request is planned and executed independently.

## Troubleshooting

**`Client.__init__() got an unexpected keyword argument 'proxies'`** — a version
mismatch between the pinned `groq` SDK and a newer `httpx`. Fixed by pinning
`httpx==0.27.2` in `requirements.txt` (already applied in this repo).

**Getting placeholder text like `[Content pending...]` in the generated docx** —
this means a task hit its retry limit and fell back safely rather than crashing.
Usually indicates `GROQ_API_KEY` isn't set correctly in `.env`, or the key has no
remaining quota. Check the server logs for the specific error each task hit.
