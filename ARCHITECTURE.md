# aiRA — Architecture Document

## 1. Problem & approach

Build an assistant that answers natural-language questions about an unfamiliar codebase —
including both **local** questions ("how does auth work?", "which APIs create users?") and
**global** ones ("explain the architecture", "which files do I change to add a feature?").

The approach is **Retrieval-Augmented Generation (RAG)**: index an uploaded project into
searchable chunks, retrieve the most relevant ones for each question, and have an LLM answer
**only from that retrieved context**, always citing the source files. This grounds answers in
the actual code (no fine-tuning, no hallucinated APIs) and makes the system work on any project
without retraining.

## 2. System overview

```
React (Vite)  ──HTTPS/SSE──►  Flask REST API  ──►  Postgres (Neon) + pgvector
   Vercel                       Render (native            users/projects/chats/jobs
                                Python, no Docker)         + PGVector per-project collections
                                  │  ├─ JWT auth
                                  │  ├─ in-process worker (Postgres-as-queue)
                                  │  └─ retrieval + prompt
                                  ▼
                         Embeddings API (Jina)     LLM cascade (Groq)
```

One set of models everywhere — **Jina embeddings + a 4-model Groq cascade** — identical in dev
and prod. Local and production differ only in environment variables (`DATABASE_URL`, `APP_ENV`,
`FRONTEND_ORIGIN`), never in code, giving full dev/prod parity.

## 3. Major components

**Frontend (React + Vite).** Auth screen, project dashboard with upload and live indexing
status (polls while a project is `INDEXING`), and a streaming chat with a citations/evidence
panel. Consumes the SSE stream via `fetch` + `ReadableStream` (the stream endpoint is an
authenticated POST, which `EventSource` can't do).

**API (Flask, app-factory).** Blueprints for auth, projects, and chat. JWT auth; a consistent
JSON error layer (`ApiError`); CORS locked to the frontend origin in prod. Thin routes delegate
to a service layer.

**Persistence (Postgres + pgvector on Neon).** One database holds relational data *and*
vectors — no separate vector service. The app's own tables are `users/projects/chats/jobs`;
chunk vectors live in LangChain PGVector's own per-project collections (`project_<id>`), not in
an application table. Embeddings are **1024-dim (Jina) in both dev and prod**.

**Background indexing (Postgres-as-queue + in-process worker).** Upload returns `202`
immediately after saving the ZIP and enqueuing a `jobs` row. A worker thread claims jobs with
`SELECT … FOR UPDATE SKIP LOCKED`, so N concurrent workers never double-process. Retries are
bounded; a boot-recovery sweep requeues jobs left `RUNNING` by a crash/restart. No Redis/Celery.

**Indexing pipeline.** Safe ZIP extraction (path-traversal + zip-bomb guards) → file
classification (skip vendored/binary) → chunking (Tree-sitter syntax-aware for 10 languages,
line-window fallback otherwise, so no file is dropped) → chunks become LangChain `Document`s
added to the project's PGVector collection (batched) → repo map (file tree + per-file signatures
+ README/frameworks, built with **zero LLM calls**).

**Retrieval.** PGVector cosine similarity returns a candidate pool, then a **Jina cross-encoder
reranker** (LangChain `JinaRerank`) reorders it and keeps the top-K. A **confidence check** (max
cosine similarity + a breadth heuristic) decides whether to attach the structural context card —
not a brittle keyword router.

**LLM cascade.** LangChain **ChatGroq** drives the Groq cascade: the primary model is built with
`.with_fallbacks([...])`, so LangChain auto-fails-over to the next model on error. Groq limits are
per-model, so the 4-model chain multiplies effective free throughput.

## 4. Request flows

**Upload → index:** `POST /api/projects` saves ZIP → enqueues job → returns 202. Worker:
extract → chunk → embed (batched) → store → build repo map → `READY` (or `FAILED` with reason).

**Ask (per question, HLD §2.1):** embed query → PGVector similarity pool → rerank → confidence check →
(if weak/broad) attach context card / repo map → build a context-constrained prompt → stream
the answer from the cascade → return citations (file, lines, score, snippet) + a "why these
sources" note → persist the turn.

## 5. Key design decisions & trade-offs

| Decision | Why | Trade-off |
|---|---|---|
| RAG (not fine-tuning) | Grounded, citable, works on any repo, free | Answer quality bounded by retrieval quality |
| LangChain for the RAG pipeline | Industry-standard, composable, less bespoke code (PGVector/ChatGroq/JinaRerank/LCEL) | Heavier deps / version churn |
| Cross-encoder reranker for result ordering | Reorders the vector candidate pool by true query relevance, which the top-K depends on | An extra rerank API call per question |
| pgvector in Postgres | Free, persistent, one fewer service | Not a specialized vector DB (fine at this scale) |
| Postgres-as-queue (not Celery/Redis) | Durable async on one free box, no extra service | Polling latency; not a full broker |
| Confidence-based context (not keyword routing) | Robust to any phrasing | A tuned threshold, not a learned classifier |
| Jina embeddings (dev == prod) | Removes PyTorch → runs on a free non-Docker host; full parity | Network hop + embedding-API rate limits |
| Render native Python (not Docker/HF) | Simplest free deploy, no container to maintain | Free tier sleeps (cold starts) |
| Same models dev == prod | One code path, full parity, no "works locally, breaks in prod" | Dev needs the API keys; shares Groq's per-account quota |
| Zero-LLM repo map | Global-question context without burning rate limits | Signatures, not deep semantic summaries |

## 6. Failure handling

Corrupt/empty/oversized/path-traversal ZIPs fail fast (`PermanentJobError`, no wasted retries);
transient errors retry with backoff; jobs surviving a crash are recovered on boot; unsupported
files fall back to window chunking; "no relevant chunks" and the system prompt guardrail prevent
fabricated answers; the LLM cascade fails over on rate limits.

## 7. Scale considerations

Async indexing keeps uploads instant; embeddings + inserts are streamed in batches to bound
memory; `WORKER_CONCURRENCY` parallelizes indexing (safe via SKIP LOCKED); each project's vectors
live in their own PGVector collection, so every search scans only that project's chunks; a single
shared, pre-pinged connection pool serves all collections. Horizontal scale-out (multiple worker
processes / a managed queue) is a config/infra change, not a rewrite.

## 8. Challenges encountered

- **Free-tier without Docker:** local embedding models forced a heavy host; solved by offloading
  prod embeddings to an API so the backend runs as plain Python.
- **Global vs local questions:** pure top-K under-serves architecture questions; solved with a
  confidence-gated repo map built without LLM calls (rate-limit safe).
- **Per-model rate limits:** solved with a model cascade — `ChatGroq(...).with_fallbacks([...])`
  advances to the next model on error, keyed on the per-model quota structure.
- **Serverless-Postgres connections:** Neon closes idle connections; a single shared,
  pre-pinged connection pool (reused across all PGVector collections) keeps retrieval robust
  under load instead of building a new pool per query.

## 9. What I'd improve with more time

Incremental re-indexing and GitHub import; an optional lexical retriever combined with the
vector search via LangChain's `EnsembleRetriever`; cross-project search; per-user
quotas/rate-limiting; and moving indexing to a dedicated worker service for true horizontal
scale.
