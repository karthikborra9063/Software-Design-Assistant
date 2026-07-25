"""Repo map + project context card (HLD-v2 §2.3) — built with ZERO LLM calls.

Everything here is deterministic:
- file tree (from the walk)
- per-file signature skeleton (reuses the symbol names already found during chunking)
- README excerpt + detected entrypoints/frameworks (filename heuristics)
- dominant language

The compact `context_card` is attached to weak/broad questions; the fuller `repo_map` is used
by the escalation hop. Neither is embedded — both are fetched by project_id.
"""

import os
from collections import Counter

from .files import SourceFile, read_text

# Filenames that signal an entrypoint or a framework/build system.
ENTRYPOINT_NAMES = {
    "main.py", "app.py", "wsgi.py", "asgi.py", "manage.py", "__main__.py",
    "index.js", "index.ts", "server.js", "app.js", "main.go", "main.rs", "main.java",
}
FRAMEWORK_MARKERS = {
    "package.json": "Node.js/JS", "requirements.txt": "Python", "pyproject.toml": "Python",
    "go.mod": "Go", "pom.xml": "Java/Maven", "build.gradle": "Java/Gradle",
    "cargo.toml": "Rust", "dockerfile": "Docker", "docker-compose.yml": "Docker Compose",
}

README_EXCERPT_CHARS = 2000
MAX_TREE_ENTRIES = 300


def _readme_excerpt(files: list[SourceFile]) -> str | None:
    for f in files:
        if os.path.basename(f.rel_path).lower().startswith("readme"):
            text = read_text(f.abs_path)
            if text:
                return text[:README_EXCERPT_CHARS]
    return None


def build_repo_map(files: list[SourceFile], chunks: list[dict]) -> tuple[dict, dict, str | None]:
    """Return (context_card, repo_map, dominant_language)."""
    # Dominant code language (also used for Project.language).
    lang_counts = Counter(f.language for f in files if f.category == "code" and f.language)
    dominant_language = lang_counts.most_common(1)[0][0] if lang_counts else None

    # Signatures per file, reused from chunk metadata (names + types, no re-parsing).
    signatures: dict[str, list[dict]] = {}
    for c in chunks:
        if c.get("symbol_name"):
            signatures.setdefault(c["file_path"], []).append(
                {"type": c["chunk_type"], "name": c["symbol_name"], "line": c["start_line"]}
            )

    tree = sorted(f.rel_path for f in files)[:MAX_TREE_ENTRIES]

    entrypoints = sorted(
        f.rel_path for f in files if os.path.basename(f.rel_path).lower() in ENTRYPOINT_NAMES
    )
    frameworks = sorted(
        {
            label
            for f in files
            for marker, label in FRAMEWORK_MARKERS.items()
            if os.path.basename(f.rel_path).lower() == marker
        }
    )

    context_card = {
        "file_tree": tree,
        "readme_excerpt": _readme_excerpt(files),
        "entrypoints": entrypoints,
        "frameworks": frameworks,
        "languages": dict(lang_counts),
        "total_files": len(files),
    }
    repo_map = {"signatures": signatures}
    return context_card, repo_map, dominant_language
