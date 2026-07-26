# DesignMind — AI Software Design Assistant

Upload a software project (as a `.zip`) and ask natural-language questions about it. DesignMind
indexes the codebase with a Retrieval-Augmented Generation (RAG) pipeline and answers **grounded
in the actual source**, citing the files it used — so you can see *why* it answered.

It handles the kinds of questions in the challenge — *"How does authentication work?"*, *"Where
is the payment flow?"*, *"Which APIs create users?"*, *"Explain the architecture"*, *"Which files
should I change to add a feature?"*, *"How is data stored?"*, *"Summarize the project structure"* —
plus meta questions like *"How many files are in this project?"* and *"What languages are used?"*.

**Live demo (frontend):** `https://<your-app>.vercel.app`
**Backend health:** [`https://aira-backend-ur3p.onrender.com/api/health`](https://aira-backend-ur3p.onrender.com/api/health)
**No demo credentials needed** — just register an account on the site.

> Design & rationale: **[`ARCHITECTURE.md`](ARCHITECTURE.md)** (system design, components, decisions, trade-offs, challenges, future work).

---

## What it does
- **Register / log in** (JWT auth), then upload one or more projects as `.zip`.
- Each project is **indexed in the background**; the dashboard shows live status until **Ready**.
- **Ask questions** and get streamed, Markdown-formatted answers grounded in the code, ending
  with the file(s) the answer came from.
- **Conversation memory** — follow-up questions ("where is it used?", "no, I meant registration")
  are resolved against the recent thread.

## Tech stack (100% free-tier, no Docker)
Local dev and production run the **same models** — only environment values differ (full dev/prod parity).

| Layer | Technology |
|---|---|
| Frontend | React (Vite) → **Vercel** |
| Backend + worker | Flask (native Python) → **Render** (`gunicorn`) |
| RAG framework | **LangChain** (PGVector, ChatGroq, JinaRerank, LCEL) |
| Job queue | Postgres-as-queue (no Redis/Celery) |
| Database + vectors | **Neon** PostgreSQL + pgvector |
| Parsing / chunking | Tree-sitter (+ line-window fallback) |
| Retrieval | PGVector similarity → **Jina** cross-encoder reranker |
| Embeddings | **Jina** `jina-embeddings-v3` (1024-dim), via a LangChain `Embeddings` wrapper |
| LLM | **Groq** cascade (`ChatGroq`): qwen3.6-27b → gpt-oss-120b → llama-3.3-70b → llama-3.1-8b |

## Repository layout
```
Software-Design-Assistant/
├── backend/
│   ├── app/
│   │   ├── __init__.py        # Flask application factory
│   │   ├── config.py          # all config from env vars
│   │   ├── models/            # SQLAlchemy models: user, project, chat, job
│   │   ├── indexing/          # extraction, file classification, Tree-sitter chunking, repo map
│   │   ├── services/          # embedding, vectorstore, retrieval, prompt, llm, qa, indexing, queue
│   │   ├── api/               # HTTP blueprints: health, auth, projects, chat
│   │   └── worker.py          # background indexing worker (threads)
│   ├── wsgi.py                # entrypoint (gunicorn / dev server); starts the worker
│   ├── requirements.txt       # runtime deps  (requirements-local.txt adds pytest)
│   └── .env.example           # copy to .env (gitignored)
├── frontend/                  # React + Vite SPA (Auth, Dashboard, Sidebar, Chat, ProfileMenu)
├── render.yaml                # Render Blueprint (backend deploy)
└── ARCHITECTURE.md            # architecture document
```

---

## Run locally

### 1. Clone
```bash
git clone https://github.com/karthikborra9063/Software-Design-Assistant.git
cd Software-Design-Assistant
```

### 2. Get free API keys (all free, no credit card)
- **Neon** Postgres → https://neon.tech (create a database; copy the *pooled* connection string)
- **Jina** embeddings key → https://jina.ai/embeddings
- **Groq** API key → https://console.groq.com

### 3. Backend (Flask + worker)
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

# create your .env from the template, then fill in the values from step 2
cp .env.example .env            # Windows: copy .env.example .env
#   DATABASE_URL, EMBED_API_KEY (Jina), LLM_1..4_API_KEY (Groq), SECRET_KEY, JWT_SECRET

# one-time: enable pgvector + create tables
export FLASK_APP=app            # Windows: set FLASK_APP=app
flask init-db

python wsgi.py                  # API + background worker on http://localhost:5000
# verify: http://localhost:5000/api/health  ->  {"status":"ok","service":"aira-backend"}
```

### 4. Frontend (React)
```bash
cd ../frontend
npm install
npm run dev                     # http://localhost:5173  (Vite proxies /api to the backend)
```
Open http://localhost:5173, register, and you're in.

### 5. Run the tests (optional)
```bash
cd backend
pip install -r requirements-local.txt
pytest
```

---

## Example usage
1. **Register** an account and log in.
2. **Upload** a project: give it a name, drag-and-drop (or browse) a source `.zip`
   (zip *without* `node_modules`/`.git`/`dist` — those are skipped anyway and just bloat the upload).
3. Wait for the status badge to turn **Ready** (indexing runs in the background).
4. **Ask**, e.g.:
   - "How does authentication work?"
   - "Which APIs are responsible for creating a user?"
   - "Explain the overall architecture of this project."
   - "Which files should I modify to add a new feature?"
   - "How many files are in this project?" · "What languages are used?"
5. Answers **stream in**, are formatted (code blocks are copyable), and end with the source file(s).

---

## Deployment & hosting choices

The app is deployed across four free services, chosen so the whole thing costs **$0**, needs
**no Docker**, and keeps each concern independently swappable:

| Piece | Host | Why this choice |
|---|---|---|
| **Frontend** | **Vercel** | Purpose-built for React/Vite; global CDN, auto-deploys from GitHub, generous free tier. |
| **Backend + worker** | **Render** (native Python) | Runs Flask + gunicorn + the in-process worker with no container to build/maintain; free web service. |
| **Database + vectors** | **Neon** (serverless Postgres + pgvector) | One store for relational data *and* embeddings → no separate vector DB; free and persistent. |
| **Embeddings** | **Jina API** | Hosted embeddings mean **no PyTorch/model weights** on the server → the backend fits Render's 512 MB free tier. |
| **LLM** | **Groq API** | Fast, free inference; per-model rate limits are multiplied by our 4-model fallback cascade. |

**Deployment flow (from GitHub):**
- **Backend (Render):** New → Blueprint → pick this repo (it reads [`render.yaml`](render.yaml)).
  Fill the secret env vars (`DATABASE_URL`, `EMBED_API_KEY`, `LLM_1..4_API_KEY`, `FRONTEND_ORIGIN`).
  The start command runs `flask init-db` (idempotent) then `gunicorn`.
- **Frontend (Vercel):** New Project → import the repo → **Root Directory = `frontend`** →
  set `VITE_API_URL` to the Render backend URL → deploy. Then set the backend's `FRONTEND_ORIGIN`
  to the Vercel URL (CORS).

**Reproduce the deployment locally:** follow *Run locally* above — it's the **same code path** as
production; only the env values differ.

### Environment variables (secrets excluded)
| Variable | Where | Notes |
|---|---|---|
| `APP_ENV` | both | `development` / `production` (controls CORS + debug) |
| `DATABASE_URL` | both | Neon connection string (use the **pooled** endpoint) |
| `SECRET_KEY`, `JWT_SECRET` | both | random strings (Render can auto-generate) |
| `FRONTEND_ORIGIN` | prod | Vercel URL, for CORS lockdown (`*` for a quick demo) |
| `EMBED_BASE_URL` / `EMBED_MODEL` / `EMBED_DIM` | both | `https://api.jina.ai/v1` / `jina-embeddings-v3` / `1024` |
| `EMBED_API_KEY` | both | Jina key |
| `LLM_n_PROVIDER/BASE_URL/API_KEY/MODEL` | both | the Groq cascade (same key ×4) |
| `WORKER_CONCURRENCY` | both | parallel indexing threads (default 1) |
| `MAX_UPLOAD_MB` / `MAX_REPO_FILES` / `TOP_K` / `CONFIDENCE_THRESHOLD` | both | tuning knobs |

---

## Assumptions
- Users upload **source archives** (we still guard against zip bombs / path traversal), ideally
  zipped **without** dependencies/build output (`node_modules`, `.git`, `dist`).
- The **raw ZIP is not persisted** — it's extracted, indexed, then discarded; only vectors + metadata remain.
- Local and prod use the **same models** (Jina + Groq); both need internet + the two free API keys.
- One project is active per chat; cross-project search is out of scope for v1.

## Known limitations
- **Free-tier scale:** Neon ~0.5 GB storage; Render's free instance **sleeps when idle** (30–60 s
  cold start) and has 512 MB RAM.
- **Upload caps:** ZIP ≤ 200 MB; ≤ 2,000 indexed files (beyond that, a bounded subset is indexed
  and flagged); ≤ 60,000 archive entries.
- **Retrieval is vector + cross-encoder reranker** (no lexical BM25); exact-identifier matches rely
  on embeddings + the reranker.
- **Groq free tier** has a per-model daily token budget; very heavy usage can exhaust the cascade.
- Answers are only as good as retrieval; the model is instructed to say **"not found"** rather than
  guess, so some questions are declined by design.

## Future improvements
Incremental re-indexing + GitHub import · optional hybrid (lexical + vector) retrieval via
LangChain `EnsembleRetriever` · cross-project search · per-user quotas / rate-limiting · a
dedicated worker service for true horizontal scale · indexing-truncation surfaced in the UI.

## Security note
`.env` is gitignored — **never commit real API keys or database URLs**. In production, secrets are
provided via the Render/Vercel dashboards, not the repo.
