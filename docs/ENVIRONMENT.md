# Environment Specification

Every environment variable used by this project, its purpose, and whether
it carries a secret. See `.env.example` (repo root) for a copy-pasteable
template with placeholder values.

## Backend (`backend/`, loaded via `config.py` per `ARCHITECTURE.md` §3)

| Name | Purpose | Required? | Example placeholder | Used in | Secret? |
|---|---|---|---|---|---|
| `GROQ_API_KEY` | Authenticates calls to the Groq LLM API | Required | `gsk_REPLACE_WITH_YOUR_KEY` | `retrieval/generation.py` | **Yes** |
| `QDRANT_URL` | Endpoint of the Qdrant Cloud cluster | Required | `https://REPLACE.cloud.qdrant.io:6333` | `retrieval/vector_store.py` | Sensitive (not a credential itself, but reveals your cluster endpoint — treat as private) |
| `QDRANT_API_KEY` | Authenticates calls to Qdrant Cloud | Required | `REPLACE_WITH_YOUR_QDRANT_KEY` | `retrieval/vector_store.py` | **Yes** |
| `CORS_ALLOWED_ORIGIN` | The single frontend origin allowed to call this API | Required | `http://localhost:5173` (dev) / `https://your-app.pages.dev` (prod) | `main.py` CORS middleware | No |
| `EMBEDDING_MODEL_NAME` | Which sentence-transformers model to load locally | Optional (default: `sentence-transformers/all-MiniLM-L6-v2`) | `sentence-transformers/all-MiniLM-L6-v2` | `ingestion/embed.py` | No |
| `LLM_MODEL_NAME` | Which Groq-hosted model to call | Optional (default: `qwen/qwen3.8-27b` — ADR-08; Groq's free-tier catalog changes over time, re-verify with `client.models.list()` before assuming a hardcoded name is still valid) | `qwen/qwen3.8-27b` | `retrieval/generation.py` | No |
| `PORT` | Port the ASGI server binds to | Required in production (provided automatically by Render) | `8000` (local dev default) | `uvicorn` start command | No |

## Frontend (`frontend/`, build-time only, Vite convention)

| Name | Purpose | Required? | Example placeholder | Used in | Secret? |
|---|---|---|---|---|---|
| `VITE_API_BASE_URL` | Base URL of the deployed FastAPI backend | Required | `http://localhost:8000` (dev) / `https://your-backend.onrender.com` (prod) | API client module | No — a public URL, safe to appear in the built bundle |

Frontend env vars live in their own `frontend/.env.example` once the
`frontend/` directory exists (implementation phase) — not duplicated here.

## Local vs. Production Configuration

| Variable | Local development | Production |
|---|---|---|
| `CORS_ALLOWED_ORIGIN` | `http://localhost:5173` | The deployed Cloudflare Pages URL (or custom domain) |
| `VITE_API_BASE_URL` | `http://localhost:8000` | The deployed Render backend URL |
| `PORT` | `8000` (or any free local port) | Provided automatically by Render — do not hard-code |
| `GROQ_API_KEY` / `QDRANT_URL` / `QDRANT_API_KEY` | A developer's own free-tier keys, in a local untracked `.env` | Set via Render's dashboard, never in a committed file |

## Acceptance Criteria Check

- **No real credentials are included:** every example value above is an
  obviously-placeholder string.
- **Every required variable is documented:** all seven backend variables and
  the one frontend variable currently known to the architecture are listed.
- **Local and production configuration are distinguished:** see the table
  above.
