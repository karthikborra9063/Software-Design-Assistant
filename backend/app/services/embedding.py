"""Embedding client — a LangChain `Embeddings` implementation.

Calls a hosted, OpenAI-compatible embeddings API (Jina). Texts are grouped into batches sized
by an approximate token budget; a shared, thread-safe throttle limits requests to a
tokens-per-minute budget across all workers; rate-limited requests are retried with backoff.
Process-wide singleton.

It subclasses `langchain_core.embeddings.Embeddings` so it plugs straight into PGVector and any
other LangChain component, while adding the TPM throttle that LangChain's built-in embedders
lack (indexing a large repo would otherwise blow the Jina rate limit).
"""

import threading
import time
from collections import deque

from langchain_core.embeddings import Embeddings

from ..config import Config


def _estimate_tokens(text: str) -> int:
    # Rough heuristic: ~4 characters per token. Good enough for pacing.
    return max(1, len(text) // 4)


def _token_batches(texts: list[str], budget: int):
    """Yield (batch_texts, batch_tokens), each batch's estimated tokens <= budget."""
    batch: list[str] = []
    tokens = 0
    for t in texts:
        tt = _estimate_tokens(t)
        if batch and tokens + tt > budget:
            yield batch, tokens
            batch, tokens = [], 0
        batch.append(t)
        tokens += tt
    if batch:
        yield batch, tokens


def _is_rate_limit(exc: Exception) -> bool:
    return (
        getattr(exc, "status_code", None) == 429
        or exc.__class__.__name__ == "RateLimitError"
        or "rate" in str(exc).lower()
        and "limit" in str(exc).lower()
    )


class EmbeddingClient(Embeddings):
    def __init__(self, cfg: dict):
        from openai import OpenAI

        self.model = cfg["model_id"]
        self.dim = cfg["dim"]
        self._api = OpenAI(base_url=cfg["base_url"], api_key=cfg["api_key"])
        self._tpm = cfg["tpm"]                 # tokens-per-minute budget (with headroom)
        self._batch_tokens = cfg["batch_tokens"]  # max estimated tokens per request

        # Shared trailing-60s token window (thread-safe) so concurrent workers stay under TPM.
        self._lock = threading.Lock()
        self._window: deque[tuple[float, int]] = deque()
        self._used = 0

    def _reserve(self, tokens: int) -> None:
        """Block until sending `tokens` keeps us under the per-minute budget, then record them."""
        while True:
            with self._lock:
                now = time.monotonic()
                while self._window and now - self._window[0][0] > 60:
                    self._used -= self._window.popleft()[1]
                if not self._window or self._used + tokens <= self._tpm:
                    self._window.append((now, tokens))
                    self._used += tokens
                    return
                wait = 60 - (now - self._window[0][0])
            time.sleep(min(max(wait, 0.5), 60))

    def _embed_request(self, batch: list[str], attempts: int = 5) -> list[list[float]]:
        for attempt in range(attempts):
            try:
                resp = self._api.embeddings.create(model=self.model, input=batch)
                return [d.embedding for d in resp.data]
            except Exception as e:
                if _is_rate_limit(e) and attempt < attempts - 1:
                    time.sleep(min(60, 10 * (2**attempt)))  # 10, 20, 40, 60s backoff
                    continue
                raise

    # --- LangChain Embeddings interface ---

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed many texts, token-batched and throttled. Order is preserved."""
        out: list[list[float]] = []
        for batch, tokens in _token_batches(texts, self._batch_tokens):
            self._reserve(tokens)
            out.extend(self._embed_request(batch))
        return out

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_client: EmbeddingClient | None = None
_client_lock = threading.Lock()


def get_embedding_client() -> EmbeddingClient:
    """Return the shared singleton so ALL workers share one throttle window."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:  # double-checked locking
                _client = EmbeddingClient(Config.EMBEDDING)
    return _client
