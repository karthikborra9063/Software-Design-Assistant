"""Central configuration — everything is read from environment variables.

Design rules:
- No secrets hard-coded. Values come from a local `.env` (dev) or the Render dashboard (prod).
- LOCAL vs DEPLOYMENT differ ONLY in these values, never in code. The single behavioral
  switch is APP_ENV (controls CORS lockdown / debug).
- The embedding provider and the LLM cascade are both env-driven and pluggable.
"""

import os
import tempfile
from datetime import timedelta

from dotenv import load_dotenv

# Load backend/.env in local development. In production the platform injects real env vars.
load_dotenv()


def _normalize_db_url(url: str) -> str:
    """Neon/Heroku hand out `postgres://...`; SQLAlchemy needs `postgresql://...`."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _build_embedding_config() -> dict:
    """Embedding endpoint config — a hosted OpenAI-compatible API (Jina), same in dev and prod.

    base_url/api_key/model fully specify the endpoint; EMBED_DIM fixes the pgvector column size.
    """
    return {
        "base_url": os.environ.get("EMBED_BASE_URL", "https://api.jina.ai/v1"),
        "api_key": os.environ.get("EMBED_API_KEY", ""),
        "model_id": os.environ.get("EMBED_MODEL", "jina-embeddings-v3"),
        "dim": int(os.environ.get("EMBED_DIM", "1024")),
        # Embedding request pacing.
        "tpm": int(os.environ.get("EMBED_TPM", "90000")),          # tokens/minute budget
        "batch_tokens": int(os.environ.get("EMBED_BATCH_TOKENS", "8000")),  # max tokens/request
    }


def _build_llm_cascade() -> list[dict]:
    """Read LLM_1_*, LLM_2_*, ... into an ordered priority list of model configs.

    Position == priority. The client tries index 0 first and advances to the next model on
    rate-limit (HTTP 429) or unavailability. Same code for one model or the full Groq cascade.
    """
    cascade: list[dict] = []
    i = 1
    while True:
        model_id = os.environ.get(f"LLM_{i}_MODEL")
        if not model_id:  # stop at the first gap
            break
        cascade.append(
            {
                "provider": os.environ.get(f"LLM_{i}_PROVIDER", "groq"),
                "base_url": os.environ.get(
                    f"LLM_{i}_BASE_URL", "https://api.groq.com/openai/v1"
                ),
                "api_key": os.environ.get(f"LLM_{i}_API_KEY", ""),
                "model_id": model_id,
                # Optional per-model reasoning_effort (e.g. "none" for reasoning models like
                # Qwen3). Left unset when the env var is absent.
                "reasoning_effort": os.environ.get(f"LLM_{i}_REASONING_EFFORT") or None,
            }
        )
        i += 1
    return cascade


class Config:
    # --- Environment separation (local vs deployed) ---
    APP_ENV = os.environ.get("APP_ENV", "development")
    IS_PRODUCTION = APP_ENV == "production"
    # Dev allows any origin; prod locks CORS to the deployed frontend (e.g. the Vercel URL).
    FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")

    # --- Core Flask / auth secrets ---
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET", "dev-jwt-secret-change-me")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(
        hours=int(os.environ.get("JWT_EXPIRES_HOURS", "12"))
    )

    # --- Database ---
    SQLALCHEMY_DATABASE_URI = _normalize_db_url(
        os.environ.get("DATABASE_URL", "postgresql://aira:aira@localhost:5432/aira")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Neon (serverless Postgres) closes idle connections; pre_ping revives a stale one instead of
    # erroring, and recycle retires connections before Neon does. Applies to the app's own engine.
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 300}
    # LangChain's PGVector store uses the psycopg3 driver; SQLAlchemy (the rest of the app) uses
    # psycopg2. Same database, different dialect prefix.
    PGVECTOR_CONNECTION = SQLALCHEMY_DATABASE_URI.replace(
        "postgresql://", "postgresql+psycopg://", 1
    )

    # --- Upload / archive limits (all env-configurable) ---
    # Compressed ZIP size — Flask rejects bodies larger than this.
    MAX_UPLOAD_MB = int(os.environ.get("MAX_UPLOAD_MB", "50"))
    MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
    # Uncompressed-size ceiling (zip-bomb guard).
    MAX_UNCOMPRESSED_MB = int(os.environ.get("MAX_UNCOMPRESSED_MB", "300"))
    MAX_UNCOMPRESSED_BYTES = MAX_UNCOMPRESSED_MB * 1024 * 1024
    # Hard ceiling on TOTAL archive entries (extraction-cost guard).
    MAX_ARCHIVE_ENTRIES = int(os.environ.get("MAX_ARCHIVE_ENTRIES", "20000"))
    # Cap on how many files we actually index (bounds chunks/storage regardless of repo size).
    MAX_REPO_FILES = int(os.environ.get("MAX_REPO_FILES", "2000"))
    # Temp dir for uploaded ZIPs (deleted after indexing). Cross-platform default.
    UPLOAD_TMP = os.environ.get("UPLOAD_TMP") or os.path.join(
        tempfile.gettempdir(), "aira_uploads"
    )

    # --- Embeddings (pluggable; dim fixes the pgvector column) ---
    EMBEDDING = _build_embedding_config()
    EMBED_DIM = EMBEDDING["dim"]

    # --- Retrieval tuning ---
    TOP_K = int(os.environ.get("TOP_K", "10"))
    # Reranking: the Jina cross-encoder (a LangChain document compressor) reorders the vector
    # candidate pool by true query relevance before the top-K are sent to the LLM. Reuses the
    # embeddings API key.
    RERANK = {
        "enabled": os.environ.get("RERANK_ENABLED", "1") != "0",
        "api_key": os.environ.get("RERANK_API_KEY") or os.environ.get("EMBED_API_KEY", ""),
        "model": os.environ.get("RERANK_MODEL", "jina-reranker-v2-base-multilingual"),
    }
    RERANK_POOL = int(os.environ.get("RERANK_POOL", "30"))       # candidates fed to the reranker
    # Below this max cosine similarity we treat chunk retrieval as "weak" and attach the
    # structural project context card (see HLD-v2 §2.1).
    CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.45"))
    # Conversation memory: how many recent turns to replay to the model and to consider when
    # reformulating a follow-up question into a standalone search query.
    HISTORY_WINDOW = int(os.environ.get("HISTORY_WINDOW", "3"))

    # --- Background worker ---
    # Number of concurrent indexing worker threads. The Postgres queue uses
    # FOR UPDATE SKIP LOCKED, so N threads never process the same job. Default 1 keeps memory
    # bounded on the small prod instance; set higher (e.g. 3) locally to index several projects
    # in parallel.
    WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", "1"))

    # --- LLM cascade (ordered) ---
    LLM_CASCADE = _build_llm_cascade()
