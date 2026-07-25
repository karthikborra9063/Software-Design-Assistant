"""Indexing package: turn an uploaded ZIP into retrievable, embedded chunks + a repo map.

Modules:
- extraction: safe ZIP extraction (path-traversal / zip-bomb guards)
- files:      walk + classify files (code / doc / config; skip binaries & vendored dirs)
- chunking:   Tree-sitter syntax-aware chunks + line-window fallback
- repo_map:   file tree + per-file signatures + heuristics (zero LLM) for global questions
"""
