"""Token-budget batching for the embedding client (pure — no network)."""

from app.services.embedding import _estimate_tokens, _token_batches


def test_batches_respect_token_budget():
    # Each text ~25 tokens (100 chars). Budget 60 -> at most 2 texts per batch.
    texts = ["x" * 100 for _ in range(5)]
    batches = list(_token_batches(texts, budget=60))
    assert all(tokens <= 60 or len(batch) == 1 for batch, tokens in batches)
    # every text is included exactly once
    assert sum(len(b) for b, _ in batches) == 5


def test_single_oversized_text_still_emitted():
    big = "y" * 100_000  # far over budget
    batches = list(_token_batches([big], budget=100))
    assert len(batches) == 1 and len(batches[0][0]) == 1


def test_estimate_tokens_monotonic():
    assert _estimate_tokens("") >= 1
    assert _estimate_tokens("a" * 400) > _estimate_tokens("a" * 4)
