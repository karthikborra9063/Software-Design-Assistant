"""Reasoning-model <think> stripping (blocking + streaming). Pure, no network."""

from app.services.llm import ThinkFilter, strip_think


def test_strip_complete_think_block():
    assert strip_think("<think>chain of thought</think>The answer.") == "The answer."


def test_strip_unclosed_think():
    assert strip_think("Intro. <think>still reasoning") == "Intro."


def test_passthrough_without_think():
    assert strip_think("Just a normal answer.") == "Just a normal answer."


def test_stream_filter_removes_think_across_chunk_boundaries():
    f = ThinkFilter()
    out = ""
    for piece in ["<thi", "nk>secret rea", "soning</think>Final ", "answer."]:
        out += f.feed(piece)
    out += f.flush()
    assert "secret" not in out
    assert "Final answer." in out
