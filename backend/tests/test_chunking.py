"""Chunking: Tree-sitter code chunks + the always-there fallback."""

from app.indexing.chunking import chunk_file

PY = '''\
import os


def foo(x):
    return x + 1


class Bar:
    def method(self):
        return 2
'''


def test_code_chunks_have_named_definitions():
    chunks = chunk_file(PY, "code", "python", "sample.py")
    names = {c["symbol_name"] for c in chunks if c["symbol_name"]}
    assert "foo" in names          # top-level function
    assert "Bar" in names          # class (small -> emitted whole)
    assert all(c["file_path"] == "sample.py" for c in chunks)
    assert all(c["start_line"] <= c["end_line"] for c in chunks)


def test_unsupported_or_doc_falls_back_to_windows():
    text = "\n".join(f"line {i}" for i in range(20))
    chunks = chunk_file(text, "doc", None, "README.md")
    assert len(chunks) >= 1
    assert chunks[0]["chunk_type"] == "doc"


def test_no_file_is_ever_dropped():
    # Even gibberish that fails to parse as code still yields a fallback chunk.
    chunks = chunk_file("(((not valid code", "code", "python", "broken.py")
    assert len(chunks) >= 1
