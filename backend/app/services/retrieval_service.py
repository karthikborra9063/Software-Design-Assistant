"""Retrieval orchestration (HLD-v2 §2.1).

For every question: pull a candidate pool from the project's PGVector collection (cosine
similarity), rerank it with the Jina cross-encoder, and keep the top-K. Then decide — from
retrieval confidence, NOT keyword routing — whether to also attach the project's structural
context card. Strong chunk scores → chunks only (local). Weak scores or a breadth signal →
attach the context card / repo map (global).
"""

from dataclasses import dataclass, field

from langchain_community.document_compressors import JinaRerank
from langchain_core.documents import Document

from ..config import Config
from ..models import Project
from .vectorstore import get_vectorstore

_SNIPPET_CHARS = 320

# Breadth signal — forces the context card even if some chunk scored high. Covers structural
# questions AND meta/aggregate questions (counts, listings, languages) that vector search can't
# answer — those are served from the precomputed project stats + file tree in the context card.
_BROAD_TERMS = (
    "architecture", "structure", "overview", "high level", "high-level", "the project",
    "overall", "summarize", "summary", "how does the project", "which files", "where should",
    "add a feature", "add a new feature", "tech stack", "components", "organized",
    # meta / aggregate:
    "how many", "number of", "list all", "list the", "language", "languages",
    "lines of code", "total files", "file count", "how many files", "how many functions",
)


@dataclass
class RetrievalResult:
    items: list[dict]                 # ranked chunks (with score, content, metadata)
    used_context_card: bool           # whether structural context was attached
    broad: bool                       # breadth heuristic fired
    max_similarity: float             # top cosine similarity (confidence signal)
    context_card: dict | None = None  # project overview, when attached
    repo_map: dict | None = field(default=None)  # signatures, when attached (broad questions)


def _is_broad(question: str) -> bool:
    q = question.lower()
    return any(term in q for term in _BROAD_TERMS)


def _rerank(question: str, candidates: list[Document], top_k: int) -> list[Document]:
    """Reorder candidates by true query relevance (Jina cross-encoder), keep top_k.

    On any failure (or when reranking is disabled) fall back to the vector order — the
    candidates already arrive sorted by cosine similarity.
    """
    if Config.RERANK["enabled"] and candidates:
        try:
            compressor = JinaRerank(
                model=Config.RERANK["model"],
                jina_api_key=Config.RERANK["api_key"],
                top_n=top_k,
            )
            reranked = compressor.compress_documents(candidates, question)
            if reranked:
                return list(reranked)
        except Exception:
            pass  # fall through to vector order
    return candidates[:top_k]


def _item(doc: Document, fallback_score: float | None) -> dict:
    md = doc.metadata or {}
    # Reranked docs carry the cross-encoder score; otherwise use the vector similarity.
    score = md.get("relevance_score", fallback_score)
    return {
        "file_path": md.get("file_path", ""),
        "language": md.get("language"),
        "chunk_type": md.get("chunk_type"),
        "symbol_name": md.get("symbol_name"),
        "start_line": md.get("start_line"),
        "end_line": md.get("end_line"),
        "score": round(float(score), 4) if score is not None else None,
        "content": doc.page_content,
        "snippet": doc.page_content[:_SNIPPET_CHARS],
    }


def retrieve(project: Project, question: str) -> RetrievalResult:
    top_k = Config.TOP_K
    threshold = Config.CONFIDENCE_THRESHOLD

    store = get_vectorstore(project.id)
    # Candidate pool with cosine distance; similarity = 1 - distance (matches the old scale).
    scored = store.similarity_search_with_score(question, k=Config.RERANK_POOL)
    candidates = [doc for doc, _ in scored]
    sim_by_content = {id(doc): 1.0 - float(dist) for doc, dist in scored}
    max_similarity = max(sim_by_content.values(), default=0.0)

    ranked = _rerank(question, candidates, top_k)
    items = [_item(doc, sim_by_content.get(id(doc))) for doc in ranked]

    broad = _is_broad(question)
    weak = max_similarity < threshold
    used_card = broad or weak or not items  # attach structural context when chunks are weak/broad

    return RetrievalResult(
        items=items,
        used_context_card=used_card,
        broad=broad,
        max_similarity=round(max_similarity, 4),
        context_card=project.context_card if used_card else None,
        repo_map=project.repo_map if (used_card and broad) else None,
    )
