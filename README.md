# aiRA — AI Software Design Assistant

Upload a software project (ZIP) and ask natural-language questions about it. aiRA indexes the
codebase with a Retrieval-Augmented Generation (RAG) pipeline and answers with **citations to
the source files** plus the retrieved evidence, so you can see *why* it answered.

**Live demo:** _<add your Vercel URL here after deploying>_ &nbsp;·&nbsp; **API:** _<Render URL>/api/health_

> Design rationale: [`HLD-v2.md`](HLD-v2.md). Architecture write-up: [`ARCHITECTURE.md`](ARCHITECTURE.md).
> Implementation reference: [`IMPLEMENTATION.md`](IMPLEMENTATION.md).
> No demo credentials are needed — just register an account on the site.

## Stack (all free-tier, no Docker)
Local dev and production use the **same models** — only `DATABASE_URL` / `APP_ENV` /
`FRONTEND_ORIGIN` differ.

| Layer | Technology |
|---|---|
| Frontend | React (Vite) → Vercel |
| Backend + worker | Flask (native Python) → Render (`gunicorn`) |
| Job queue | Postgres-as-queue (no Redis) |
| DB + vectors | Neon PostgreSQL + pgvector (separate DB per env) |
| Parsing | Tree-sitter (+ fallback chunker) |
| Framework | LangChain (RAG pipeline) |
| Retrieval | LangChain PGVector (pgvector) + Jina cross-encoder reranker |
| **Embeddings** | **Jina** `jina-embeddings-v3` (1024-dim), via a LangChain Embeddings wrapper |
| **LLM** | LangChain **ChatGroq** cascade: qwen3.6-27b → gpt-oss-120b → llama-3.3-70b → llama-3.1-8b |

One codebase, one set of models everywhere — full dev/prod parity.

## Repository layout
```
aira/
├── backend/
│   ├── app/
│   │   ├── __init__.py         # Flask application factory
│   │   ├── config.py           # all config from env (APP_ENV, embeddings, LLM cascade)
│   │   ├── extensions.py       # db / migrate / jwt / cors singletons
│   │   ├── models/             # SQLAlchemy models (user, project, chat, job)
│   │   ├── indexing/           # extraction, files, Tree-sitter chunking, repo map
│   │   ├── services/           # embedding, vectorstore, retrieval, prompt, llm, qa, indexing
│   │   └── api/                # HTTP blueprints (health, auth, projects, chat)
│   ├── wsgi.py                 # entrypoint (gunicorn / dev server)
│   ├── requirements.txt        # runtime deps (torch-free)
│   ├── requirements-local.txt  # + pytest for running the tests
│   └── .env.example            # copy to .env (gitignored) — Jina + Groq
└── frontend/                  # React + Vite SPA
    ├── src/
    │   ├── api.js              # API client (incl. SSE-over-fetch reader)
    │   ├── AuthContext.jsx     # JWT/auth state
    │   ├── App.jsx             # auth screen vs dashboard
    │   └── components/         # Auth, Dashboard, Sidebar, Chat (+ citations)
    ├── vite.config.js          # dev proxy /api -> backend
    └── .env.example            # VITE_API_URL (prod backend URL)
```

## Prerequisites (all free)
1. **Neon** Postgres — https://neon.tech (use a **separate DB/branch** for local vs prod).
2. **Jina** embedding key — https://jina.ai/embeddings
3. **Groq** API key — https://console.groq.com

## Run locally (no Docker)
```powershell
cd "aira\backend"
python -m venv .venv
.\.venv\Scripts\Activate.ps1            # if blocked: Set-ExecutionPolicy -Scope Process RemoteSigned
pip install -r requirements.txt         # runtime deps (add -r requirements-local.txt for tests)

Copy-Item .env.example .env             # set DATABASE_URL (Neon), EMBED_API_KEY (Jina),
                                        # LLM_*_API_KEY (Groq), SECRET_KEY, JWT_SECRET.

$env:FLASK_APP = "app"                  # one-time DB setup: enable pgvector + create tables
flask init-db                           # -> "Initialized database ... (vector dim=1024)."

python wsgi.py                          # runs the API + background worker
# verify: http://localhost:5000/api/health  ->  {"status":"ok","service":"aira-backend"}
```
(macOS/Linux: `source .venv/bin/activate`, `cp .env.example .env`, `export FLASK_APP=app`.)

Run `flask init-db` once per database (once for your local Neon dev branch, once for prod).

## Run the frontend (local)
```powershell
cd "aira\frontend"
npm install
npm run dev        # http://localhost:5173  (Vite proxies /api to the backend on :5000)
```
Register an account, upload a codebase `.zip`, wait for status **Ready**, then ask questions.

## Deployment (Render — native Python, no Docker)
- **Build:** `pip install -r requirements.txt` (torch-free)
- **Start:** `gunicorn -w 1 --threads 4 -t 300 wsgi:app`
- Env vars set in the Render dashboard: `APP_ENV=production`, `EMBED_API_KEY` (Jina), the Groq
  LLM cascade keys, `DATABASE_URL` (Neon), `FRONTEND_ORIGIN` (Vercel URL). Most non-secret
  values are prefilled by `render.yaml`.

### Deploy the backend (Render)
1. Push this repo to GitHub. In Render → **New → Blueprint**, select the repo; it reads
   [`render.yaml`](render.yaml) (native Python, no Docker).
2. Fill the `sync: false` secrets in the dashboard: `DATABASE_URL` (a **separate** Neon `main`
   branch — see note below), `FRONTEND_ORIGIN` (your Vercel URL), `EMBED_API_KEY` (Jina), and
   `LLM_1..4_API_KEY` (the same Groq key in all four).
3. Deploy. The start command runs `flask init-db` (idempotent) then gunicorn.

> **Note:** use a **separate Neon database/branch** for prod vs local so their data doesn't mix
> (both are 1024-dim now, so the schema is identical either way).

### Deploy the frontend (Vercel)
1. Vercel → **New Project** → import the repo, set **Root Directory = `frontend`**
   (uses [`vercel.json`](frontend/vercel.json)).
2. Set env var `VITE_API_URL` to the Render backend URL.
3. Deploy, then set the backend's `FRONTEND_ORIGIN` to the resulting Vercel URL.

## Environment variables
| Var | Where | Notes |
|---|---|---|
| `APP_ENV` | both | `development` / `production` (controls CORS + debug) |
| `DATABASE_URL` | both | Neon connection string (use the **pooled** endpoint) |
| `SECRET_KEY`, `JWT_SECRET` | both | random strings (Render can auto-generate) |
| `FRONTEND_ORIGIN` | prod | Vercel URL, for CORS lockdown |
| `EMBED_BASE_URL` / `EMBED_MODEL` / `EMBED_DIM` | both | `https://api.jina.ai/v1` / `jina-embeddings-v3` / `1024` |
| `EMBED_API_KEY` | both | Jina key |
| `LLM_n_PROVIDER/BASE_URL/API_KEY/MODEL` | both | the Groq cascade (same key ×4) |
| `WORKER_CONCURRENCY` | both | parallel indexing threads (default 1) |
| `MAX_UPLOAD_MB`, `MAX_REPO_FILES`, `TOP_K`, `CONFIDENCE_THRESHOLD` | both | tuning knobs |

## Assumptions
- One project is active per chat session; cross-project search is out of scope (v1).
- Uploaded projects are trusted-ish source archives (we still guard against zip bombs / path
  traversal), zipped **without** dependencies/build output (`node_modules`, `.git`, `dist`).
- The raw ZIP is not persisted — only extracted, indexed, then discarded.
- Local and prod use the same models (Jina + Groq); both need internet + the two free API keys.
  Groq's per-account quota is shared across environments (fine at evaluation traffic).

## Known limitations
- **Free-tier scale:** Neon ~0.5 GB storage (~10–20 medium projects); Render free instance
  **sleeps when idle** (30–60s cold start) and is 512 MB RAM.
- **Upload caps:** ZIP ≤ 50 MB; ≤ 2,000 indexable files (beyond that, a bounded subset is
  indexed and a warning is logged); ≤ 20,000 total archive entries.
- **Retrieval is vector + cross-encoder reranker** (no lexical BM25); exact-identifier matches
  rely on embeddings + the reranker.
- **Embedding rate limits** (Jina) can slow indexing of large repos in prod (absorbed by the
  async queue).
- Answers are only as good as retrieval; the model is instructed to say "not found" rather than
  guess, so some questions may be declined.

## Future improvements
Incremental re-indexing + GitHub import · optional hybrid BM25 via LangChain `EnsembleRetriever` ·
cross-project search · per-user quotas/rate-limiting · a dedicated worker service for horizontal
scale.

## Security note
`.env` is gitignored. Never commit real API keys or database URLs. In production, secrets are
provided via the Render dashboard, not the repo.
