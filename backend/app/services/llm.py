"""LLM cascade built on LangChain's ChatGroq (HLD-v2 §6).

`get_llm()` returns the primary Groq model with every other configured model attached as an
automatic fallback via `.with_fallbacks()` — LangChain retries the next model on any error
(rate-limit, unavailability), which replaces the hand-rolled failover loop.

`get_planner_llm()` returns just the last (cheapest) model, used for the query-reformulation
step, where we want a single cheap call and no fallback.

Some Groq models are "reasoning" models that emit their chain-of-thought inside <think>…</think>
in the content. `strip_think()` / `ThinkFilter` remove it so only the final answer reaches the
user (a safety net even when `reasoning_effort="none"` is configured).
"""

import re

from langchain_groq import ChatGroq

from ..config import Config
from ..errors import ApiError

_TEMPERATURE = 0.1  # low — we want grounded, deterministic answers, not creativity
_MAX_TOKENS = 1024

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_HOLDBACK = len("</think>")  # chars held back while streaming to avoid emitting a partial tag


def strip_think(text: str) -> str:
    """Remove complete <think> blocks; also drop an unclosed trailing one."""
    text = _THINK_RE.sub("", text)
    open_idx = text.find("<think>")
    if open_idx != -1:
        text = text[:open_idx]
    return text.strip()


class ThinkFilter:
    """Streaming filter: yields answer text with <think> reasoning removed, tag-safe across
    token boundaries by holding back the last few characters until flush."""

    def __init__(self):
        self._raw = ""
        self._emitted = 0

    def _clean(self) -> str:
        t = _THINK_RE.sub("", self._raw)
        open_idx = t.find("<think>")
        return t[:open_idx] if open_idx != -1 else t

    def feed(self, piece: str) -> str:
        self._raw += piece
        clean = self._clean()
        end = max(self._emitted, len(clean) - _HOLDBACK)
        out = clean[self._emitted : end]
        self._emitted = end
        return out

    def flush(self) -> str:
        clean = self._clean()
        out = clean[self._emitted :]
        self._emitted = len(clean)
        return out


def _build_chat(m: dict) -> ChatGroq:
    """One ChatGroq model from a cascade config entry."""
    kwargs = {
        "model": m["model_id"],
        "api_key": m["api_key"],
        "temperature": _TEMPERATURE,
        "max_tokens": _MAX_TOKENS,
    }
    base = (m.get("base_url") or "").rstrip("/")
    # ChatGroq/the Groq SDK append the "/openai/v1/chat/completions" path themselves, so
    # base_url must be the host root. Our env carries the full OpenAI-compatible base
    # (…/openai/v1) for the embedding client — strip that suffix here to avoid a doubled path.
    if base.endswith("/openai/v1"):
        base = base[: -len("/openai/v1")]
    if base:
        kwargs["base_url"] = base
    if m.get("reasoning_effort"):  # e.g. "none" for Qwen3 to skip chain-of-thought
        kwargs["reasoning_effort"] = m["reasoning_effort"]
    return ChatGroq(**kwargs)


def get_llm():
    """Primary model, with the remaining cascade as automatic fallbacks (tried in order)."""
    cascade = Config.LLM_CASCADE
    if not cascade:
        raise ApiError("No language model is configured.", 500)
    chats = [_build_chat(m) for m in cascade]
    primary, *rest = chats
    return primary.with_fallbacks(rest) if rest else primary


def get_planner_llm() -> ChatGroq:
    """Model for query reformulation. No fallback — caller handles errors.

    Uses the second-to-last cascade entry when available (a mid-tier instruction-follower like
    llama-3.3-70b) rather than the smallest model: reformulation is one short call per follow-up,
    so correctness matters more than shaving its cost, and the smallest model tends to
    over-compress specific questions into vague topics.
    """
    cascade = Config.LLM_CASCADE
    if not cascade:
        raise ApiError("No language model is configured.", 500)
    return _build_chat(cascade[-2] if len(cascade) >= 2 else cascade[-1])
