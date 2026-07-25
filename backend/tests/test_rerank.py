"""Reranker fallback behaviour (pure — no network).

Reranking itself is delegated to LangChain's JinaRerank (a cross-encoder API). Here we only
verify our fallback: when reranking is disabled, `_rerank` keeps the vector order and truncates
to top_k without calling out.
"""

from langchain_core.documents import Document

from app.config import Config
from app.services import retrieval_service as rs


def _docs(n):
    return [Document(page_content=f"doc {i}", metadata={"file_path": f"f{i}.py"}) for i in range(n)]


def test_disabled_rerank_keeps_vector_order_and_truncates(monkeypatch):
    monkeypatch.setitem(Config.RERANK, "enabled", False)
    candidates = _docs(5)
    out = rs._rerank("any query", candidates, top_k=3)
    assert out == candidates[:3]  # same objects, vector order preserved


def test_empty_candidates_returns_empty(monkeypatch):
    monkeypatch.setitem(Config.RERANK, "enabled", True)
    assert rs._rerank("q", [], top_k=5) == []
