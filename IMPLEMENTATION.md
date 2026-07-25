# aiRA — Implementation Reference

A precise description of the system as it is currently implemented: components, data model,
request flows, configuration, and API. (For design rationale see `HLD-v2.md`.)

---

## 1. Overview

aiRA lets a developer upload a software project (ZIP) and ask natural-language questions about
it. The backend indexes the code with a Retrieval-Augmented Generation (RAG) pipeline built on
LangChain; each answer is generated only from retrieved project context and streamed to the UI,
ending with the file location(s) of the relevant implementation.

Two capabilities define the behavior:
- **RAG Q&A** over an individual project (vector retrieval + cross-encoder reranking → LLM answer).
- **Conversation memory** so follow-up questions build on the recent thread.

---

## 2. Technology stack

| Layer | Technology |
|---|---|
| Frontend | React (Vite) |
| Backend | Python, Flask (application-factory) |
| Auth | JWT (Flask-JWT-Extended), Werkzeug password hashing (pbkdf2:sha256) |
| Database | PostgreSQL (Neon) |
| Vector store | LangChain **PGVector** on Postgres — one collection per project |
| ORM / driver | SQLAlchemy 2 (app tables, psycopg2); psycopg3 (PGVector engine) |
| Background jobs | Postgres-as-queue + in-process worker threads (no Redis/Celery) |
| Parsing | Tree-sitter (+ line-window fallback) |
| Embeddings | Jina API (`jina-embeddings-v3`, 1024-dim), wrapped as a LangChain `Embeddings` |
| Reranker | Jina cross-encoder via LangChain `JinaRerank` |
| LLM | LangChain `ChatGroq` cascade (`with_fallbacks`): qwen3.6-27b → gpt-oss-120b → llama-3.3-70b → llama-3.1-8b |
| RAG framework | LangChain — PGVector, ChatGroq, JinaRerank, composed with LCEL |

The same models are used in local and deployed environments; only environment values differ.

---

## 3. Repository structure

```
aira/
├── backend/
│   ├── app/
│   │   ├── __init__.py        # create_app() factory: extensions, error handlers, blueprints
│   │   ├── config.py          # all configuration from environment variables
│   │   ├── extensions.py      # db, migrate, jwt, cors singletons
│   │   ├── errors.py          # ApiError, PermanentJobError, JSON error handlers
│   │   ├── cli.py             # `flask init-db`
│   │   ├── worker.py          # background worker threads
│   │   ├── models/            # SQLAlchemy models: user, project, chat, job
│   │   ├── api/               # HTTP blueprints: health, auth, projects, chat, deps
│   │   ├── indexing/          # extraction, files, chunking (Tree-sitter), repo_map
│   │   └── services/          # embedding, vectorstore, retrieval, prompt_builder, llm,
│   │                          #   qa, indexing, auth, project, queue
│   ├── wsgi.py                # entrypoint; starts the worker
│   ├── requirements.txt       # runtime deps
│   └── requirements-local.txt # + pytest
└── frontend/                  # React + Vite SPA
```

---

## 4. Data model

The application's own tables live in one PostgreSQL database; deleting a parent cascades to its
children. Chunk vectors are stored separately by LangChain PGVector (see below).

- **users** — `id`, `name`, `email` (unique), `password_hash`, `created_at`.
- **projects** — `id`, `user_id`, `name`, `status` (`UPLOADING|INDEXING|READY|FAILED`),
  `language`, `total_files`, `total_chunks`, `failure_reason`, `context_card` (JSONB),
  `repo_map` (JSONB), `created_at`, `indexed_at`.
- **chats** — `id`, `user_id`, `project_id`, `question`, `answer`, `citations` (JSONB),
  `created_at`.
- **jobs** — `id`, `project_id`, `type`, `status` (`PENDING|RUNNING|DONE|FAILED`), `attempts`,
  `error`, `payload` (JSONB), `created_at`, `started_at`, `finished_at`. Indexed on
  `(status, created_at)`.

**Chunk vectors** are not an application table: LangChain PGVector stores each project's chunks —
page content + embedding + metadata (`file_path`, `language`, `chunk_type`, `symbol_name`,
`start_line`, `end_line`) — in its own collection named `project_<id>`. That collection plus the
project's `context_card` and `repo_map` support retrieval; the raw uploaded ZIP is not persisted.

---

## 5. Backend components

**Application factory** (`app/__init__.py`) — builds the Flask app, binds extensions, registers
the JSON error handlers and the health/auth/projects/chat blueprints, and exposes the
`flask init-db` command.

**Configuration** (`app/config.py`) — reads everything from environment variables: DB URL, auth
secrets, upload/archive limits, embedding endpoint, retrieval tuning, conversation-memory
(history) setting, the worker concurrency, and the ordered LLM cascade. It also derives the
psycopg3 connection string PGVector uses.

**Auth** (`api/auth.py`, `services/auth_service.py`) — registration and login validate input,
hash passwords with pbkdf2:sha256, and issue a JWT whose subject is the user id. `api/deps.py`
resolves the current user from the JWT for protected routes.

**Projects** (`api/projects.py`, `services/project_service.py`) — upload validates the `.zip`,
stores it to a temp path, creates a `Project` (status `INDEXING`), enqueues an index job, and
returns immediately. List/get/delete enforce that a project belongs to the requesting user;
delete also drops the project's PGVector collection.

**Queue** (`services/queue.py`) — the `jobs` table is the queue. Jobs are claimed with
`SELECT … FOR UPDATE SKIP LOCKED`; failures retry up to `MAX_ATTEMPTS`, then mark `FAILED`; a
boot-recovery sweep resets jobs left `RUNNING` past a timeout back to `PENDING`.

**Worker** (`app/worker.py`) — `WORKER_CONCURRENCY` daemon threads (started from `wsgi.py`) poll
the queue and run the indexing pipeline. On success the temp ZIP is deleted; on permanent
failure the project is marked `FAILED` with a reason.

**Indexing pipeline** (`indexing/` + `services/indexing_service.py`):
1. `extraction.py` — safely extracts the ZIP: rejects path-traversal entries, enforces
   entry-count and uncompressed-size limits, and skips vendored/build/VCS directories so they
   are never written or counted.
2. `files.py` — walks the extracted tree and classifies each file as code (with a Tree-sitter
   language), doc, or config; skips binaries, lock files, and oversized files; caps the number
   of indexed files.
3. `chunking.py` — code files are chunked by Tree-sitter (functions/methods/classes, splitting
   oversized ones); docs/config and any unparseable file use an overlapping line-window
   fallback, so every file yields at least one chunk.
4. Chunks are wrapped as LangChain `Document`s and added to the project's PGVector collection in
   batches; PGVector embeds each batch via the embedding client as it inserts. Opening the store
   with `pre_delete=True` first makes re-indexing idempotent.
5. `repo_map.py` — builds the `context_card` (file tree, README excerpt, entrypoints,
   frameworks, language mix) and `repo_map` (per-file signature skeletons) with no LLM calls.
6. The project is marked `READY` with its stats.

**Embedding client** (`services/embedding.py`) — a LangChain `Embeddings` implementation
(process-wide singleton) that calls the Jina embeddings API. Requests are grouped into
token-bounded batches and paced by a shared tokens-per-minute throttle; rate-limited requests are
retried with backoff. Because it implements the `Embeddings` interface, PGVector uses it directly.

**Vector store** (`services/vectorstore.py`) — a factory that opens a LangChain `PGVector`
instance for a project's collection (`project_<id>`). All instances share one pre-pinged
SQLAlchemy engine (psycopg3), so retrieval never builds a new connection pool per query.

**Retrieval** (`services/retrieval_service.py`):
- `PGVector.similarity_search_with_score` returns a candidate pool for the project by cosine
  similarity.
- LangChain `JinaRerank` (a cross-encoder document compressor) reorders the pool by true query
  relevance and keeps the top `TOP_K`. If reranking is disabled or errors, the vector order is
  used as-is.
- Computes a confidence signal (max cosine similarity) and a breadth heuristic; when retrieval
  is weak or the question is broad, the project's `context_card` (and, for broad questions, the
  `repo_map`) is attached.
- Returns ranked chunks (with scores + snippets) and the attached structural context.

**Prompt builder** (`services/prompt_builder.py`) — exposes `ANSWER_PROMPT`, a LangChain
`ChatPromptTemplate` (system prompt + history placeholder + human message) used by the LCEL
chain, plus `format_context()` which turns a retrieval result into the context string. The system
prompt requires answers grounded only in the provided context (no inventing files/behavior; code
is included only when the user asks for a specific function's implementation; the answer ends with
a single line naming the file(s), and omits that line entirely when the information was not found).

**LLM client** (`services/llm.py`) — builds the Groq cascade with LangChain `ChatGroq`.
`get_llm()` returns the primary model wrapped in `.with_fallbacks([...])`, so the chain
auto-advances to the next model on error; `get_planner_llm()` returns a mid-tier model used for
query reformulation. Reasoning-model output wrapped in `<think>…</think>` is stripped
(`strip_think` / `ThinkFilter`), and a model may set `reasoning_effort` per its config entry.

**Q&A orchestration** (`services/qa_service.py`) — ties retrieval → prompt → LLM together with an
LCEL chain, applies conversation memory (Section 6), builds the citations, persists each turn, and
exposes `answer()` (JSON) and `answer_stream()` (SSE).

---

## 6. Request flows

### 6.1 Authentication
`POST /api/auth/register` or `/login` validate credentials, hash/verify the password, and return
a JWT plus the user object. Subsequent requests send `Authorization: Bearer <token>`;
`GET /api/auth/me` validates the token and returns the user.

### 6.2 Upload and indexing
1. `POST /api/projects` (multipart: `name`, `file`) → validates, saves the ZIP, creates the
   project (`INDEXING`), enqueues an index job, returns `202` with the project.
2. A worker thread claims the job and runs the indexing pipeline (Section 5). Status transitions
   `INDEXING → READY` (or `FAILED`).
3. The frontend polls `GET /api/projects` while any project is indexing to update its status.

### 6.3 Asking a question
Handled by `qa_service` for both `POST /api/projects/<id>/ask` (JSON) and
`/ask/stream` (SSE). `validate_ask` first requires the project to be `READY` and the question
non-empty.

**Conversation memory.** The last `HISTORY_WINDOW` (3) turns of this user+project are loaded. If
there are prior turns, a mid-tier model reformulates the latest message into a standalone search
query — resolving pronouns/short phrases and applying corrections ("no, I meant X"), while
preserving the concrete terms the user wrote, and returning the message unchanged when it is
already self-contained. Retrieval then runs on that query, and the recent turns are replayed to
the answering model as chat history. With no prior turns, retrieval runs on the question as-is.

**Answer generation.** An LCEL chain — `ANSWER_PROMPT | ChatGroq cascade` — is invoked with the
formatted context, the question, and the history. For `/ask` the answer is returned as JSON with
citations and metadata; for `/ask/stream` the same chain is streamed and the response is SSE:
`meta` (citations + explanation) → `token`* → `done` (or `error`). Each turn (question, answer,
citations) is persisted to `chats`.

---

## 7. Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` / `production` (controls CORS lockdown and debug) |
| `FRONTEND_ORIGIN` | allowed CORS origin in production |
| `SECRET_KEY`, `JWT_SECRET`, `JWT_EXPIRES_HOURS` | Flask/JWT auth |
| `DATABASE_URL` | PostgreSQL connection string (pooled endpoint recommended) |
| `MAX_UPLOAD_MB` | compressed ZIP size limit |
| `MAX_UNCOMPRESSED_MB` | uncompressed-size limit |
| `MAX_ARCHIVE_ENTRIES` | total entries allowed in a ZIP |
| `MAX_REPO_FILES` | number of files actually indexed |
| `EMBED_BASE_URL`, `EMBED_API_KEY`, `EMBED_MODEL`, `EMBED_DIM` | embedding endpoint (Jina) |
| `EMBED_TPM`, `EMBED_BATCH_TOKENS` | embedding rate pacing |
| `TOP_K`, `CONFIDENCE_THRESHOLD` | retrieval size and context-card threshold |
| `RERANK_ENABLED`, `RERANK_MODEL`, `RERANK_POOL` | Jina reranker toggle, model, and candidate pool size |
| `HISTORY_WINDOW` | conversation memory: recent turns replayed + used to reformulate a follow-up |
| `WORKER_CONCURRENCY` | number of indexing worker threads |
| `LLM_n_PROVIDER/BASE_URL/API_KEY/MODEL` (+ optional `LLM_n_REASONING_EFFORT`) | ordered cascade |

`flask init-db` enables the pgvector extension and creates the application tables; PGVector
creates its per-project collections automatically on first index.

---

## 8. API reference

| Method | Route | Auth | Description |
|---|---|---|---|
| GET | `/api/health` | — | Liveness check |
| POST | `/api/auth/register` | — | Create account → JWT + user |
| POST | `/api/auth/login` | — | Log in → JWT + user |
| GET | `/api/auth/me` | JWT | Current user |
| POST | `/api/projects` | JWT | Upload ZIP → `202`, background indexing |
| GET | `/api/projects` | JWT | List the user's projects (with status) |
| GET | `/api/projects/<id>` | JWT | Fetch one project |
| DELETE | `/api/projects/<id>` | JWT | Delete a project and its data |
| POST | `/api/projects/<id>/ask` | JWT | Answer (JSON) with citations |
| POST | `/api/projects/<id>/ask/stream` | JWT | Answer (SSE stream) |
| GET | `/api/projects/<id>/chats` | JWT | Chat history for the project |

---

## 9. Frontend

A React (Vite) single-page app:
- **Auth** — register/login; the JWT is stored in `localStorage` and validated on load.
- **Dashboard** — a sidebar lists the user's projects with live status badges (polled while
  indexing) and an upload form; the main panel is the chat for the selected project.
- **Chat** — loads history, sends questions to the streaming endpoint, and renders answers
  token-by-token as they arrive. Input is enabled only when the project is `READY`.

In development, Vite proxies `/api` to the backend; in production the API base URL is set via
`VITE_API_URL`.

---

## 10. Running locally

```
cd backend
python -m venv .venv && .venv\Scripts\Activate.ps1     # (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
copy .env.example .env                                 # fill DATABASE_URL, EMBED_API_KEY, LLM_* keys, secrets
set FLASK_APP=app & flask init-db
python wsgi.py                                          # API + worker on :5000

cd ../frontend
npm install
npm run dev                                             # UI on :5173
```

Run the tests with `pytest` (after `pip install -r requirements-local.txt`).
