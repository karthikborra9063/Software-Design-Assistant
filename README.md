# DesignMind — AI Software Design Assistant

DesignMind is an AI-powered assistant that helps developers understand unfamiliar software projects.

Upload a source-code archive (`.zip`) and ask natural-language questions about the codebase. The
system indexes the project with a Retrieval-Augmented Generation (RAG) pipeline and answers
**grounded in the actual source code**, citing the relevant files — so you can see *why* it answered.

---

## Demo

🌐 **Frontend:** https://software-design-assistant.vercel.app

🩺 **Backend health:** https://aira-backend-ur3p.onrender.com/api/health

No demo credentials are required — simply register an account and upload a project.

---

## Features

- Upload software projects as ZIP archives
- Background indexing with live status updates
- AI-powered codebase question answering, grounded in the source with **file citations**
- Context-aware **follow-up conversations** (project-level memory)
- **Markdown-formatted** answers with syntax-highlighted, copyable code
- Indexes code **and** docs, config, and **HTML/CSS** — with intelligent Tree-sitter chunking
- **Repository insight / metadata queries** — project structure & file tree, file count, languages used
- Secure **JWT authentication**
- Handles large repositories, malformed archives, and rate limits gracefully

---

## Example Questions

**Architecture**
- Explain the overall architecture.
- How does authentication work?
- How is data stored and retrieved?
- Summarize the project structure.

**Code navigation**
- Where is the payment flow implemented?
- Which APIs create users?
- Which files implement authentication?
- Where is the JWT verified?

**Development**
- Which files should I modify to add feature X?
- Trace the login flow.
- Which modules are responsible for image uploads?
- Explain how user registration works.

**Repository insights**
- How many files are in this project?
- What languages are used?
- List the main files in the project.

---

## How It Works

```
            Upload ZIP
                 │
                 ▼
        Extract source files            (safe: path-traversal + zip-bomb guards)
                 │
                 ▼
      Tree-sitter code chunking          (docs/config/HTML/CSS → line-window fallback)
                 │
                 ▼
      Generate Jina embeddings           (batched, rate-limit throttled)
                 │
                 ▼
      Store in PGVector (Neon)           + build a zero-LLM repo map (tree, signatures, stats)
                 │
                 ▼
        User asks a question             (follow-ups reformulated using recent turns)
                 │
                 ▼
     Semantic retrieval (PGVector)
                 │
                 ▼
      Jina cross-encoder rerank          → top-K  (+ context card for broad/meta questions)
                 │
                 ▼
        Groq LLM generates answer        (streamed)
                 │
                 ▼
     Response + source citations
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite → Vercel |
| Backend + worker | Flask (native Python) → Render |
| Authentication | JWT |
| Database | PostgreSQL (Neon) |
| Vector store | pgvector (via LangChain PGVector) |
| Job queue | PostgreSQL job queue (no Redis/Celery) |
| Parsing / chunking | Tree-sitter (+ line-window fallback) |
| Embeddings | Jina Embeddings v3 (1024-dim) |
| Retrieval framework | LangChain |
| Reranking | Jina cross-encoder |
| LLM | Groq — `ChatGroq` model cascade with automatic fallback |

The application runs the **same code in development and production** — only environment variables differ.

---

## Repository Structure

```
Software-Design-Assistant/
├── backend/
│   ├── app/
│   │   ├── api/            # HTTP blueprints: health, auth, projects, chat
│   │   ├── indexing/       # extraction, file classification, chunking, repo map
│   │   ├── models/         # SQLAlchemy models: user, project, chat, job
│   │   ├── services/       # embedding, vectorstore, retrieval, prompt, llm, qa, queue
│   │   ├── worker.py       # background indexing worker
│   │   ├── config.py       # all configuration from environment variables
│   │   └── __init__.py     # Flask application factory
│   ├── requirements.txt
│   └── wsgi.py             # entrypoint (gunicorn / dev server)
├── frontend/               # React + Vite SPA
├── ARCHITECTURE.md         # system design, decisions, trade-offs, challenges, future work
├── render.yaml             # Render deployment blueprint
└── README.md
```

---

## Local Setup

### 1. Clone the repository
```bash
git clone https://github.com/karthikborra9063/Software-Design-Assistant.git
cd Software-Design-Assistant
```

### 2. Get free API keys (no credit card required)
- **Neon** PostgreSQL — https://neon.tech (copy the *pooled* connection string)
- **Jina AI** embeddings — https://jina.ai/embeddings
- **Groq** API — https://console.groq.com

### 3. Backend
```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt

# create your .env from the template, then fill in the values from step 2
cp .env.example .env        # Windows: copy .env.example .env
#   DATABASE_URL, EMBED_API_KEY, LLM_1..4_API_KEY, SECRET_KEY, JWT_SECRET

# one-time: enable pgvector + create tables
export FLASK_APP=app        # Windows: set FLASK_APP=app
flask init-db

python wsgi.py              # API + background worker → http://localhost:5000
# verify: http://localhost:5000/api/health  →  {"status":"ok","service":"aira-backend"}
```

### 4. Frontend
```bash
cd frontend
npm install
npm run dev                 # http://localhost:5173  (Vite proxies /api to the backend)
```
Open http://localhost:5173, register, upload a project `.zip`, wait for **Ready**, then ask questions.

### Running tests
```bash
cd backend
pip install -r requirements-local.txt
pytest
```

---

## Deployment & Hosting Choices

Deployed across four free services — chosen so the whole system costs **$0**,
and keeps each concern independently swappable:

| Piece | Host | Why |
|---|---|---|
| **Frontend** | **Vercel** | Purpose-built for React/Vite; global CDN, auto-deploys from GitHub, generous free tier. |
| **Backend + worker** | **Render** (native Python) | Runs Flask + gunicorn + the in-process worker with no container to maintain; free web service. |
| **Database + vectors** | **Neon** (serverless Postgres + pgvector) | One store for relational data *and* embeddings → no separate vector DB; free and persistent. |
| **Embeddings** | **Jina API** | Hosted embeddings mean no PyTorch/model weights on the server → the backend fits Render's 512 MB free tier. |
| **LLM** | **Groq API** | Fast, free inference; per-model daily limits are multiplied by a 4-model fallback cascade. |

- **Backend (Render):** New → Blueprint → select this repo (it reads [`render.yaml`](render.yaml)); fill
  the secret env vars; the start command runs `flask init-db` then `gunicorn`.
- **Frontend (Vercel):** New Project → import repo → **Root Directory = `frontend`** → set
  `VITE_API_URL` to the backend URL → deploy; then set the backend's `FRONTEND_ORIGIN` to the Vercel URL.
- **Reproduce locally:** the *Local Setup* above is the **same code path** as production — only env values differ.

### Environment variables (secrets excluded)
| Variable | Notes |
|---|---|
| `APP_ENV` | `development` / `production` (controls CORS + debug) |
| `DATABASE_URL` | Neon connection string (use the **pooled** endpoint) |
| `SECRET_KEY`, `JWT_SECRET` | random strings |
| `FRONTEND_ORIGIN` | allowed CORS origin in production (the Vercel URL; `*` for a quick demo) |
| `EMBED_BASE_URL` / `EMBED_MODEL` / `EMBED_DIM` | `https://api.jina.ai/v1` / `jina-embeddings-v3` / `1024` |
| `EMBED_API_KEY` | Jina key |
| `LLM_n_PROVIDER/BASE_URL/API_KEY/MODEL` | the Groq model cascade (same key ×4) |
| `WORKER_CONCURRENCY` | parallel indexing threads (default 1) |
| `MAX_UPLOAD_MB` / `MAX_REPO_FILES` / `TOP_K` / `CONFIDENCE_THRESHOLD` | tuning knobs |

---

## Architecture

The complete system architecture — indexing pipeline, retrieval flow, design decisions,
trade-offs, challenges, and future improvements — is documented in **[`ARCHITECTURE.md`](ARCHITECTURE.md)**.

---

## Assumptions

- Users upload source-code archives, ideally zipped **without** dependencies/build output
  (`node_modules`, `.git`, `dist` — these are skipped anyway).
- Archives exceeding the size/entry caps are **rejected**; a project exceeding the file cap is
  indexed as a **bounded subset** (and flagged), never silently truncated.
- Raw ZIP archives are **discarded after indexing** — only vectors + metadata are retained.
- One project is active per conversation; cross-project search is out of scope for v1.

## Known Limitations

- Render's free tier **sleeps when idle** → 30–60 s cold start on the first request.
- Neon free tier has limited storage (~0.5 GB).
- Retrieval is **semantic + cross-encoder rerank only** .
- Heavy Groq usage may exceed the free daily token quota (mitigated by the model cascade).
- Cross-project search is not supported.

## Future Improvements

- Incremental indexing · GitHub repository import
- Hybrid retrieval (BM25 + vector) via LangChain `EnsembleRetriever`
- Cross-project search · horizontal worker scaling
- Rate limiting · per-user quotas
- Clearer UI indicators when indexing is truncated

---

## Security

- Environment variables and secrets are **never committed** (`.env` is gitignored).
- JWT-based authentication; passwords stored only as pbkdf2 hashes.
- ZIP-bomb and path-traversal protection during extraction.
- Raw uploaded archives are discarded after indexing.

---

