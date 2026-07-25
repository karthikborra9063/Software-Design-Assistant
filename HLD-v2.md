# Software Design Assistant — High Level Design (v2)

> **Supersedes the original HLD.** This version is aligned with (a) every requirement and
> evaluation criterion in the AI Engineering Internship Challenge problem statement, and
> (b) a hard constraint of **100% free resources** from development through deployment
> (no paid services, no time-limited trials).
>
> This design covers: a repo-map layer for global/architectural questions, non-code + fallback
> indexing, explicit failure handling, an explainability layer, and a fully-free deployment
> stack (Vercel + Render native Python + Neon/pgvector + Jina embeddings + Groq), with NO Docker.
> The RAG pipeline is built on LangChain (PGVector, ChatGroq, JinaRerank, LCEL).

---

## 1. Project Overview

### Objective
An AI-powered assistant that lets developers upload a software project and ask natural
language questions about it. The system understands the codebase via a Retrieval-Augmented
Generation (RAG) pipeline and answers with **citations to the relevant source files**, plus
the retrieved evidence so the user can see *why* an answer was produced.

### Functional Requirements
- User registration & login (JWT auth)
- Upload software projects as ZIP
- Manage multiple uploaded projects
- Background project indexing (status-tracked)
- Natural language Q&A for a selected project
- Context-aware answers with source citations + retrieved evidence
- Public, free deployment

### Version 1 Scope
One project is active per chat session. Cross-project search is intentionally excluded
(future work). Multiple projects can be stored and switched between.

---

## 2. Retrieval Design (the key upgrade over v1)

The system must answer **any** question, not just the 7 examples. Rigid keyword routing
(local vs global) is brittle and misroutes the long tail. Instead we **retrieve first, then
decide how much context to send based on retrieval confidence** — so structural context is
paid for only when a question actually needs it (token/rate-limit discipline).

### 2.1 Per-question flow (generalized, handles arbitrary questions)
1. **Vector retrieval** — the query is embedded and a candidate pool is fetched from the
   project's PGVector collection by cosine similarity.
2. **Cross-encoder rerank** — LangChain `JinaRerank` (a Jina cross-encoder) reorders that pool
   by true query-document relevance and keeps the top-K (capped, per-chunk size truncated). The
   reranker surfaces the right chunks even when pure embedding similarity is ambiguous.
3. **Confidence check (NO LLM call)** — max similarity score + a breadth heuristic decide the
   context strategy. This is the "router", and it runs on real retrieval signal, not brittle
   keyword guessing.
4. **Assemble context by confidence — structural context is CONDITIONAL, not default:**
   - **Strong scores (local):** prompt = question **+ chunks only**. Context card is **NOT**
     sent → minimal tokens (the common case).
   - **Weak scores / breadth hit (global):** attach the compact project context card
     (see §2.3), plus the full repo map (per-file signatures) for breadth/structural questions.
5. **Answer call** — one LLM call with the assembled context.
6. **Unanswerable** — if nothing relevant is found, answer "not found in this project"
   (no hallucination).

**Rate-limit discipline:** capped `top_k` + truncated chunks; structural context sent only
when needed; **retry with backoff on HTTP 429 → automatic fallback model**. Normally **1 LLM
call** with question + capped chunks → safe under free-tier TPM/daily limits regardless of
question volume/variety.

### 2.2 Worked examples (there is NO hard local/global router)
Every question runs the same flow; divergence is driven by **retrieval confidence**, not by
classifying the question.

- **Local — "How does authentication work?"** Vector retrieval + rerank land a tight, high-score
  cluster (`login`, `verify_jwt`, `hash_password`) → prompt = question + those chunks only.
  **Context card NOT sent**; no escalation; 1 LLM call, minimal tokens.
- **Global — "Explain the architecture."** Embedding matches nothing specific → **low scores,
  scattered chunks**. Confidence check fails → attach the **project context card**, escalate to
  the **full repo map** if needed → answer from tree/frameworks/module layout.
- **Hybrid — "Which files should I modify to add a feature?"** Retrieval finds the existing
  similar feature's files (medium score) + the card shows directory conventions → LLM answers
  "follow the pattern of feature X: route in `routes/`, service in `services/`, model + migration".

**Escalation fires if any:** top score < ~0.45, OR chunks scattered/low-cohesion, OR breadth
heuristic ("architecture/structure/overview/the project/all"). A "global" question is simply
"one where chunk retrieval came back weak" — handled by the context card/repo map already on hand.

### 2.3 Repo map & project context card (ZERO index-time LLM calls)
> **Design rule (rate-limit safety):** we do **NOT** LLM-summarize every file at index time.
> On a 500-file repo that would be ~500 LLM calls to index a single project and would blow
> Groq's free-tier limits. The repo map is built from **free, deterministic** extraction.

Built at index time, all free:
1. **File tree** — directory walk.
2. **Per-file signature skeleton** — extracted from the *same* Tree-sitter parse already used
   for chunking: imports, function/class/method signatures, exported symbols, and the
   top-of-file module docstring. This is a byproduct of parsing we already do — no LLM.
3. **README / config / docs indexed verbatim** — `README*`, `package.json`,
   `requirements.txt`, `pyproject.toml`, `Dockerfile`, `docker-compose*`, route/config files.
   These already describe architecture and data storage.
4. **Heuristic role tags** — rule-based detection of entrypoints (`main`, `app.py`,
   `index.js`, `manage.py`), framework configs, and directory conventions
   (`controllers/`, `models/`, `services/`, `routes/`, `migrations/`).

**Project context card** = the *compact* subset (depth-limited file tree + README/overview
summary + entrypoints/frameworks), stored per project and looked up by `project_id` (not
embedded). Attached **only when the confidence check flags a question as weak/broad** (§2.1) —
not on every call.

**Full repo map** (all signature skeletons) is attached for structural/breadth questions,
alongside the context card. Signatures are tiny vs full source, so most repos' full map still
fits the context window; for very large repos the signature map sent to the model is capped to
the top files so the prompt stays bounded.

**Net LLM cost:** index-time = 0 (the repo map is fully deterministic — no LLM call); per
question = 1 answer call, plus 1 cheap reformulation call for follow-up questions.

---

## 3. Indexing Pipeline

Runs as a **durable background job** inside the Render web service (an in-process worker loop,
see §7), so uploads return immediately and the HTTP request never blocks on indexing.

**Durable async via Postgres-as-queue (no Redis):**
- Upload → INSERT a `jobs` row (`PENDING`) → return `202` immediately (async guaranteed).
- A worker loop claims jobs with `SELECT ... FOR UPDATE SKIP LOCKED` (safe with multiple
  pollers/gunicorn workers — no double-processing).
- Success → `DONE`; error → increment `attempts`, requeue or `FAILED` after N tries (retry).
- **Boot-recovery sweep:** on startup, `RUNNING` jobs past a timeout (killed by a restart/
  sleep) are reset to `PENDING` → crash-durability. This is what actually guarantees the work
  completes, not the worker thread itself.

Steps:
1. Validate & safely extract the ZIP (see §4).
2. Walk files; classify each as *code* (has a Tree-sitter grammar), *text/doc/config*, or
   *skip* (binary/vendored/`node_modules`/`.git`/lockfiles/images).
3. **Chunking:**
   - **Code** → Tree-sitter syntax-aware chunks (functions, classes, methods) + signature
     skeletons for the repo map.
   - **Everything else / unsupported language** → **line/token-window fallback chunker**
     (overlapping windows) so indexing *never hard-fails* on an unknown file type.
4. Wrap chunks as LangChain `Document`s and add them to the project's PGVector collection in
   batches (PGVector embeds each batch via the Jina embedding client as it inserts).
5. Build the repo map (file tree + per-file signatures + README/frameworks) — zero LLM calls.
6. Update project status.

**Indexing statuses (surfaced to the user):** `UPLOADING → INDEXING → READY | FAILED`.

---

## 4. Failure Handling & Edge Cases (new)

Directly targets the "thoughtful handling of errors, invalid inputs, and failure scenarios"
criterion.

| Scenario | Handling |
|---|---|
| Corrupt / empty ZIP | Reject on validation; project marked `FAILED` with a readable reason. |
| Path traversal (`../`) / zip-bomb | Sanitize entry paths; enforce total-uncompressed-size and file-count caps before extraction. |
| Oversized repo | Cap on files/total bytes; index a bounded subset and warn (never silently truncate). |
| Unsupported language/file | Fallback chunker (§3) — indexing continues. |
| Indexing crash | Bounded retry with backoff; on final failure → `FAILED` + reason surfaced. |
| Query before `READY` | API returns a clear "still indexing" state; UI polls status. |
| No relevant chunks found | Answer explicitly says the info was not found in this project (no fabrication). |
| LLM hallucination | Prompt constrains answers to provided context only; "not found" fallback. |
| Primary LLM rate-limited/down | Automatic fallback model (§6). |

---

## 5. Explainability

Every answer returns, alongside the prose:
- **Cited source files** (path + line ranges).
- **Retrieved evidence** — the actual chunks used, with similarity scores.
- A short **"why these files"** note (which retrieval path fired: local hybrid vs repo map).

This makes the "explain *why* it produced an answer" requirement concrete rather than a bare
file list.

---

## 6. LLM Service

- **Unified (dev == prod):** an **ordered cascade of Groq models** via LangChain `ChatGroq`, used
  the same way in local dev and production (keys in `.env` locally / the Render dashboard in prod,
  never committed). The primary model is wrapped with `.with_fallbacks([...])`, so the chain
  automatically advances to the next model on a rate-limit (HTTP 429) or error.
- **Why a cascade:** Groq rate limits (RPM/RPD/TPM/TPD) are tracked **per model**, so each
  model has its own independent quota. The primary burns its daily budget first (fallbacks fire
  only on 429), and **TPD is the binding free-tier limit** — so ordering weighs both quality and
  daily token budget.
- **Chosen chain (Groq free tier):**
  1. `qwen/qwen3.6-27b` — **primary**; code-specialized accuracy, 200K TPD.
  2. `openai/gpt-oss-120b` — fallback 1; strongest reasoning for architectural/hard questions, 200K TPD.
  3. `llama-3.3-70b-versatile` — fallback 2; strong reasoning + highest TPM (12K); 100K TPD.
  4. `llama-3.1-8b-instant` — fallback 3 / workhorse; weakest quality but 500K TPD / 14.4K RPD
     safety net so the system rarely exhausts all models.

  Combined budget ≈ **1M tokens/day, ~17.4K requests/day**. Excluded: prompt-guard/safeguard
  (classifiers, not assistants), allam-2-7b (Arabic-focused), groq/compound* (agentic w/ web
  search — would break "answer only from provided context").
- **LLM client design:** each model configured independently as
  `{provider, base_url, api_key, model_id}` in an ordered list, so the chain can mix providers/
  keys or share one, all via config with no code changes.
- **Embeddings (unified):** `jina-embeddings-v3` via the **Jina API**, wrapped as a LangChain
  `Embeddings` implementation (with a shared tokens-per-minute throttle), **1024-dim in both dev
  and prod**. No local model → no PyTorch → fits the non-Docker host, and dev/prod are identical.
  PGVector uses this embedder directly. A single embedding code path — no dev/prod branching.

Prompt template (context-constrained):
```
You are an expert software engineer analyzing a specific project.
Answer ONLY using the provided context. If the answer is not in the context,
say the information was not found in this project. Always cite the relevant source files.
```

---

## 7. Free Deployment Architecture (LOCKED)

**No Docker.** The one thing that previously forced a heavy host (HF Spaces + Docker) was
loading the embedding model locally (PyTorch, ~1GB RAM). By moving **embeddings to a hosted
API (Jina)**, the backend carries no model weights and runs as **plain Python on Render's free
tier** — no Dockerfile, no WSL, no container to maintain.

```
                React (Vite) ──►  Vercel (free)
                                    │  HTTPS / SSE
                                    ▼
                Render — native Python web service (free)
                ├─ Flask REST API + JWT auth
                └─ Worker loop (Postgres-as-queue: jobs table, no Redis)
                                    │
                 ┌──────────────────┼───────────────────┐
                 ▼                   ▼                    ▼
      Neon PostgreSQL (free)   Jina Embeddings API   Groq LLM API (free)
      ├─ users/projects/chats  (jina-embeddings-v3)  qwen3.6-27b → gpt-oss-120b
      └─ pgvector: chunks       hosted, no local model  → llama-3.3-70b → 3.1-8b
```

| Concern | Choice (free, no Docker) |
|---|---|
| Backend host | **Render native Python** — `gunicorn wsgi:app`, no image |
| Background worker | Postgres-as-queue + in-process worker loop (no Redis) |
| Embeddings / RAM | **Jina API** → no torch, fits the free 512MB instance |
| Vector store | LangChain PGVector on Neon (pgvector, persistent) |
| Relational DB | Neon (free, persistent) |
| Raw ZIP storage | **not stored** — extract → index → discard in memory |
| LLM / Frontend | Groq (ChatGroq) / Vercel |

**Trade-offs to state honestly (arch doc):** Render's free web service **sleeps after ~15 min
idle** (cold start ~30–60s); if it sleeps mid-index the in-process worker stops, and the
**boot-recovery sweep** resumes stale jobs on next wake. Single instance → no *independent*
horizontal worker scaling on the free tier (scale-out design described conceptually).
Embeddings now cross the network (a Jina key + mild index-time rate limits absorbed by the
async queue).

### Environment variables (documented, secrets excluded)
`SECRET_KEY`, `JWT_SECRET`, `DATABASE_URL` (Neon, includes pgvector), `MAX_UPLOAD_MB`,
`MAX_REPO_FILES`; **embeddings** `EMBED_PROVIDER` / `EMBED_BASE_URL` / `EMBED_API_KEY` /
`EMBED_MODEL` / `EMBED_DIM`; and an **ordered LLM cascade** numbered per model
`LLM_1_PROVIDER|BASE_URL|API_KEY|MODEL`, `LLM_2_*`, … (position = priority; client advances on
429/unavailable). Different values per environment via `.env` (local) / Render dashboard
(prod). Secrets never committed.

### Reproduce locally (no Docker)
`python -m venv` + `pip install -r requirements.txt`, copy `.env.example` → `.env` with Neon +
Jina + Groq keys, `python wsgi.py`. Same code path as production; only the env values differ.
(Same models as prod — Jina + Groq.)

---

## 8. Data Model

**Users:** `user_id`, `name`, `email`, `password_hash`, `created_at`
**Projects:** `project_id`, `user_id`, `project_name`, `status`, `language`, `total_files`,
`total_chunks`, `created_at`, `indexed_at`, `failure_reason`
*(dropped `zip_file_path` — the raw ZIP is not persisted)*
**Chats:** `chat_id`, `user_id`, `project_id`, `question`, `answer`, `citations`, `created_at`
**Chunk vectors (LangChain PGVector — one collection per project, `project_<id>`):** page
content + embedding + metadata (`file_path`, `language`, `chunk_type`, `symbol_name`,
`start_line`, `end_line`)
**Jobs (queue):** `job_id`, `project_id`, `type`, `status` (PENDING/RUNNING/DONE/FAILED),
`attempts`, `error`, `created_at`, `started_at`, `finished_at`

---

## 9. Security

JWT auth · password hashing · env-var secrets · input validation · upload size/file-count
limits · zip path-traversal & bomb guards · project isolation via `project_id` filter on
every retrieval · secrets never committed to Git.

---

## 10. Technology Stack

| Layer | Technology | Free? |
|---|---|---|
| Frontend | React.js → Vercel | ✅ |
| Backend + worker | Flask on Render (native Python, no Docker) | ✅ |
| Job queue | Postgres-as-queue (jobs table, no Redis) | ✅ |
| Auth | JWT | ✅ |
| Relational DB | Neon PostgreSQL | ✅ |
| Vector store | LangChain PGVector (pgvector in Neon) | ✅ |
| Code parser | Tree-sitter (+ fallback chunker) | ✅ |
| Reranker | Jina cross-encoder via LangChain JinaRerank | ✅ |
| Embeddings | jina-embeddings-v3 (Jina API, 1024-dim) — dev and prod | ✅ |
| LLM | LangChain ChatGroq cascade: qwen3.6-27b → gpt-oss-120b → llama-3.3-70b → 3.1-8b | ✅ |
| RAG framework | LangChain (PGVector, ChatGroq, JinaRerank, LCEL) | ✅ |

---

## 11. Design Decisions, Trade-offs, Challenges, Improvements

*(Also fulfills the Architecture Document sections the original HLD lacked.)*

**Design decisions & justification**
| Decision | Why |
|---|---|
| RAG over fine-tuning | No training cost/data; grounded, citable answers; free. |
| Tree-sitter chunking | Syntax-aware chunks preserve structure → better retrieval. |
| Repo map for global questions | Top-K alone can't answer "explain the architecture". |
| pgvector (not Chroma) | Free + persistent + one fewer service than a separate vector DB. |
| Jina API embeddings, dev == prod | Hosted (no PyTorch) → runs on a free non-Docker host; identical dev/prod schema (1024-dim). |
| Render native Python (not Docker/HF) | No container to build/maintain; light once embeddings are a hosted API. |
| Unified models (dev == prod) | One config, one code path, full dev/prod parity — no "works locally, breaks in prod". Trade-off: dev needs the keys and shares Groq's per-account quota. |
| Don't persist raw ZIP | Removes need for paid object storage; less attack surface. |
| Signature-skeleton repo map | Global context with **zero** index-time LLM calls. |

**Trade-offs considered:** managed vector DB (Qdrant free) vs pgvector → chose pgvector for
service simplicity; eager per-file LLM summaries vs a zero-LLM signature map → chose the
deterministic signature map to avoid index-time LLM calls entirely; local embeddings
(torch/HF/Docker) vs hosted embeddings (Jina/Render/no-Docker) → chose hosted to cut complexity
and RAM, accepting a network hop + embedding-API rate limits.

**Challenges:** free-tier worker/persistence/RAM constraints; keeping global-question support
within LLM rate limits; ensuring indexing never hard-fails on unknown file types.

**What I'd improve with more time:** cross-project search, GitHub import + incremental
indexing, an optional lexical retriever combined with the vector search via LangChain
`EnsembleRetriever`, code dependency-graph retrieval, and a dedicated worker service for
horizontal scale.

---

## 12. Future Enhancements
Cross-project search · GitHub repo integration · incremental indexing · team collaboration ·
optional hybrid (lexical + vector) retrieval · repository comparison · dependency-graph
retrieval · broader language grammars. *(Several deferred purely due to the free-resource
constraint, not technical difficulty.)*
