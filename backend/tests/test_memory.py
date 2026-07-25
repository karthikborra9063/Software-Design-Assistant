"""Conversation memory helpers (pure — no network).

The relatedness gate was replaced by LLM-based query reformulation. Here we cover the parts
that don't call the network: history replay, and the no-history passthrough (a standalone
question must be retrieved verbatim, never sent through the reformulator).
"""

from types import SimpleNamespace

from app.services.prompt_builder import history_messages
from app.services.qa_service import _reformulate


def test_history_messages_alternate_human_ai():
    turns = [
        SimpleNamespace(question="how does auth work", answer="It uses JWT."),
        SimpleNamespace(question="where is it stored", answer="In an httpOnly cookie."),
    ]
    msgs = history_messages(turns)
    assert [m.type for m in msgs] == ["human", "ai", "human", "ai"]
    assert msgs[0].content == "how does auth work"


def test_history_messages_skips_empty_answer():
    turns = [SimpleNamespace(question="q1", answer="")]
    assert [m.type for m in history_messages(turns)] == ["human"]


def test_reformulate_passthrough_without_history():
    # No prior turns → return the question unchanged, with no LLM call.
    q = "How does the payment webhook validate signatures?"
    assert _reformulate([], q) == q
