"""PGVector vector store (HLD-v2 §2/§6).

Each project's chunks live in their own PGVector *collection* named `project_<id>`. This gives
natural per-project isolation (retrieval never needs a metadata filter) and makes re-indexing
trivially idempotent: opening the store with `pre_delete=True` wipes the collection before the
fresh chunks are added.

The store uses LangChain's `Embeddings` implementation (our throttled Jina client), so
`add_documents` embeds text for us and `similarity_search_*` embeds the query for us.
"""

from langchain_postgres import PGVector
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from ..config import Config
from .embedding import get_embedding_client

_engine: Engine | None = None


def _get_engine() -> Engine:
    """One shared SQLAlchemy engine (psycopg3) reused by every PGVector instance.

    Passing PGVector a connection *string* would make it build a fresh engine (and connection
    pool) on every call — one per question — quickly exhausting Neon's connection budget in
    production. We create the engine once and hand it to every PGVector instead.
    `pool_pre_ping` transparently revives connections Neon dropped while idle (prevents
    "SSL connection has been closed unexpectedly"); `pool_recycle` retires them before Neon does.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(
            Config.PGVECTOR_CONNECTION,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _engine


def collection_name(project_id: int) -> str:
    return f"project_{project_id}"


def get_vectorstore(project_id: int, pre_delete: bool = False) -> PGVector:
    """Open (or create) the PGVector collection for a project.

    pre_delete=True drops any existing collection first — used at the start of (re-)indexing.
    """
    return PGVector(
        embeddings=get_embedding_client(),
        connection=_get_engine(),
        collection_name=collection_name(project_id),
        embedding_length=Config.EMBED_DIM,
        use_jsonb=True,
        pre_delete_collection=pre_delete,
    )
