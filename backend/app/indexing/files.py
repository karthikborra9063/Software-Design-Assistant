"""File discovery + classification.

Walks the extracted repo, skips vendored/binary noise, and labels each remaining file as
code (with a Tree-sitter language), doc, or config. Non-code files matter because READMEs and
configs often answer architecture/data-storage questions (HLD-v2 §2/§3).
"""

import os
from dataclasses import dataclass

# Extension -> Tree-sitter language name (tree-sitter-language-pack).
CODE_LANGUAGES = {
    ".py": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".rs": "rust",
    ".c": "c", ".h": "c",
    ".cc": "cpp", ".cpp": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
}

DOC_EXTS = {".md", ".mdx", ".rst", ".txt", ".adoc"}
CONFIG_EXTS = {
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".xml", ".gradle", ".properties",
    # Data-definition / schema files — the project's data model and API contracts.
    ".prisma", ".sql", ".graphql", ".gql", ".proto",
}
# Config-ish files identified by name (often extensionless).
CONFIG_NAMES = {
    "dockerfile", "makefile", "requirements.txt", "package.json", "pyproject.toml",
    "go.mod", "pom.xml", "build.gradle", "cargo.toml", "docker-compose.yml",
    "docker-compose.yaml", ".env.example",
}
# Auto-generated dependency lock files — huge, low-value noise; never index them.
LOCK_FILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock",
    "cargo.lock", "composer.lock", "gemfile.lock",
}

# Directories that are dependencies/build output/VCS — never useful to index.
SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env", "__pycache__",
    "dist", "build", ".next", ".nuxt", ".idea", ".vscode", "target", "vendor",
    "bin", "obj", ".mypy_cache", ".pytest_cache", ".gradle", ".cache", "coverage",
    ".turbo", "site-packages", ".terraform",
}

MAX_FILE_BYTES = 500_000  # skip very large files (generated/minified/data)


def is_in_skipped_dir(rel_path: str) -> bool:
    """True if any directory component of the path is a vendored/build/VCS dir we ignore.

    Applied during ZIP extraction so these entries are neither written to disk nor counted
    against the entry cap.
    """
    parts = rel_path.replace("\\", "/").split("/")[:-1]  # directory components only
    return any(p in SKIP_DIRS for p in parts)


@dataclass
class SourceFile:
    abs_path: str
    rel_path: str
    category: str          # "code" | "doc" | "config"
    language: str | None   # Tree-sitter language for code, else None


def _classify(path: str) -> tuple[str, str | None] | None:
    """Return (category, language) or None if the file should be skipped."""
    name = os.path.basename(path).lower()
    _, ext = os.path.splitext(name)
    # Skip dependency lock files (incl. renamed npm variants like package-lock-*.json).
    if name in LOCK_FILES or name.startswith("package-lock") or name.endswith(".lock"):
        return None
    if name in CONFIG_NAMES or ext in CONFIG_EXTS:
        return ("config", None)
    if ext in CODE_LANGUAGES:
        return ("code", CODE_LANGUAGES[ext])
    if ext in DOC_EXTS:
        return ("doc", None)
    return None


def collect_source_files(root: str, max_files: int) -> tuple[list[SourceFile], bool]:
    """Walk `root`, returning (files, truncated). `truncated` is True if the cap was hit."""
    files: list[SourceFile] = []
    truncated = False
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip-dirs in place so os.walk doesn't descend into them.
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git")]
        for fn in filenames:
            classified = _classify(fn)
            if classified is None:
                continue
            abs_path = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(abs_path) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            if len(files) >= max_files:
                truncated = True
                return files, truncated
            category, language = classified
            files.append(
                SourceFile(
                    abs_path=abs_path,
                    rel_path=os.path.relpath(abs_path, root).replace(os.sep, "/"),
                    category=category,
                    language=language,
                )
            )
    return files, truncated


def read_text(path: str) -> str | None:
    """Read a text file, or None if it looks binary / can't be read."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError:
        return None
    if b"\x00" in raw[:4096]:  # NUL byte in the head => binary
        return None
    return raw.decode("utf-8", errors="replace")
