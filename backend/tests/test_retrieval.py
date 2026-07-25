"""Retrieval building blocks (pure, no network): broad-question detection + item mapping."""

from langchain_core.documents import Document

from app.services.retrieval_service import _is_broad, _item


def test_broad_detects_architectural_questions():
    assert _is_broad("Explain the overall architecture of this project")
    assert _is_broad("Summarize the project structure")
    assert _is_broad("Which files should I modify to add a feature?")


def test_broad_ignores_local_questions():
    assert not _is_broad("How does user authentication work?")
    assert not _is_broad("Where is the login function implemented?")


def test_item_prefers_reranker_score_over_vector_similarity():
    doc = Document(
        page_content="def login(): ...",
        metadata={
            "file_path": "auth.controller.js",
            "chunk_type": "function",
            "start_line": 10,
            "end_line": 20,
            "relevance_score": 0.87,  # set by the reranker
        },
    )
    item = _item(doc, fallback_score=0.42)
    assert item["file_path"] == "auth.controller.js"
    assert item["score"] == 0.87  # reranker wins
    assert item["snippet"].startswith("def login")


def test_item_falls_back_to_vector_similarity():
    doc = Document(page_content="x", metadata={"file_path": "a.py"})
    assert _item(doc, fallback_score=0.55)["score"] == 0.55
