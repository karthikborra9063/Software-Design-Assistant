"""Chunking: split a file into retrievable units.

Code files -> Tree-sitter syntax-aware chunks (functions / methods / classes). A class that
fits in one chunk is emitted whole; an oversized class is descended into method-level chunks;
an oversized function is split by line windows. Docs/config and any unsupported or unparseable
file fall back to overlapping line windows, so **no file is ever dropped**.

Each chunk is a dict: {file_path, language, chunk_type, symbol_name, start_line, end_line, content}
"""

class ChunkType:
    """Labels a chunk's origin; stored verbatim in each vector's `chunk_type` metadata."""

    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    DOC = "doc"            # README / markdown / docs
    CONFIG = "config"      # json / yaml / toml / Dockerfile ...
    FALLBACK = "fallback"  # line/window chunk for unsupported file types


MAX_CHUNK_LINES = 200        # a definition larger than this gets split
WINDOW_LINES = 120           # window size when splitting large nodes/files
WINDOW_OVERLAP = 20          # overlap between windows (keeps context across boundaries)
FALLBACK_WINDOW = 60         # window size for docs/config/unsupported
FALLBACK_OVERLAP = 10
MAX_CONTENT_CHARS = 6000     # cap embedded text per chunk

# Per-language node types that represent chunkable definitions.
LANG_NODES: dict[str, dict[str, set]] = {
    "python": {"func": {"function_definition"}, "class": {"class_definition"}},
    "javascript": {
        "func": {"function_declaration", "method_definition", "generator_function_declaration"},
        "class": {"class_declaration"},
    },
    "typescript": {
        "func": {"function_declaration", "method_definition"},
        "class": {"class_declaration", "interface_declaration", "enum_declaration"},
    },
    "tsx": {
        "func": {"function_declaration", "method_definition"},
        "class": {"class_declaration", "interface_declaration", "enum_declaration"},
    },
    "java": {
        "func": {"method_declaration", "constructor_declaration"},
        "class": {"class_declaration", "interface_declaration", "enum_declaration"},
    },
    "go": {"func": {"function_declaration", "method_declaration"}, "class": {"type_declaration"}},
    "ruby": {"func": {"method", "singleton_method"}, "class": {"class", "module"}},
    "rust": {
        "func": {"function_item"},
        "class": {"struct_item", "impl_item", "trait_item", "enum_item"},
    },
    "c": {"func": {"function_definition"}, "class": {"struct_specifier"}},
    "cpp": {
        "func": {"function_definition"},
        "class": {"class_specifier", "struct_specifier"},
    },
}


def _truncate(text: str) -> str:
    return text if len(text) <= MAX_CONTENT_CHARS else text[:MAX_CONTENT_CHARS] + "\n… (truncated)"


def _window_text(text: str, rel_path: str, language, ctype: str, window: int, overlap: int) -> list[dict]:
    """Split raw text into overlapping line windows."""
    lines = text.splitlines()
    if not lines:
        return []
    chunks = []
    step = max(1, window - overlap)
    for start in range(0, len(lines), step):
        block = lines[start : start + window]
        if not block or not "".join(block).strip():
            continue
        chunks.append(
            {
                "file_path": rel_path,
                "language": language,
                "chunk_type": ctype,
                "symbol_name": None,
                "start_line": start + 1,
                "end_line": start + len(block),
                "content": _truncate("\n".join(block)),
            }
        )
        if start + window >= len(lines):
            break
    return chunks


def _node_name(node) -> str | None:
    field = node.child_by_field_name("name")
    if field is not None:
        return field.text.decode("utf-8", errors="ignore")
    for child in node.children:  # fallback: first identifier-ish child
        if "identifier" in child.type or child.type == "name":
            return child.text.decode("utf-8", errors="ignore")
    return None


def _node_lines(node) -> int:
    return node.end_point[0] - node.start_point[0] + 1


def chunk_code(text: str, language: str, rel_path: str) -> list[dict]:
    """Tree-sitter chunking. Returns [] if parsing/setup fails (caller falls back to windows)."""
    try:
        from tree_sitter_language_pack import get_parser
        parser = get_parser(language)
    except Exception:
        return []

    node_types = LANG_NODES.get(language, {"func": set(), "class": set()})
    func_types, class_types = node_types["func"], node_types["class"]
    source = text.encode("utf-8", errors="ignore")

    try:
        root = parser.parse(source).root_node
    except Exception:
        return []

    chunks: list[dict] = []

    def emit(node, ctype: str):
        content = source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")
        if not content.strip():
            return
        chunks.append(
            {
                "file_path": rel_path,
                "language": language,
                "chunk_type": ctype,
                "symbol_name": _node_name(node),
                "start_line": node.start_point[0] + 1,
                "end_line": node.end_point[0] + 1,
                "content": _truncate(content),
            }
        )

    def walk(node):
        for child in node.children:
            if child.type in func_types:
                if _node_lines(child) <= MAX_CHUNK_LINES:
                    emit(child, ChunkType.METHOD if child.type == "method_definition" else ChunkType.FUNCTION)
                else:
                    body = source[child.start_byte : child.end_byte].decode("utf-8", errors="ignore")
                    chunks.extend(
                        _window_text(body, rel_path, language, ChunkType.FUNCTION, WINDOW_LINES, WINDOW_OVERLAP)
                    )
            elif child.type in class_types:
                if _node_lines(child) <= MAX_CHUNK_LINES:
                    emit(child, ChunkType.CLASS)
                else:
                    walk(child)  # descend to emit methods individually
            else:
                walk(child)  # descend into modules/namespaces to find nested definitions

    walk(root)
    return chunks


def chunk_file(text: str, category: str, language: str | None, rel_path: str) -> list[dict]:
    """Entry point: pick the right strategy for a file; always returns at least a fallback."""
    if category == "code" and language:
        chunks = chunk_code(text, language, rel_path)
        if chunks:
            return chunks
        # Parsing failed or matched no definitions -> window the whole file.
        return _window_text(text, rel_path, language, ChunkType.FALLBACK, WINDOW_LINES, WINDOW_OVERLAP)

    ctype = ChunkType.DOC if category == "doc" else ChunkType.CONFIG
    return _window_text(text, rel_path, None, ctype, FALLBACK_WINDOW, FALLBACK_OVERLAP)
