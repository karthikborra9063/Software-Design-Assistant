"""File discovery/classification: keep code+docs, skip vendored/binary noise."""

from app.indexing.files import collect_source_files


def test_collects_code_and_docs_skips_vendored_and_binary(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "main.py").write_text("print(1)")
    (tmp_path / "README.md").write_text("# hello")
    # noise that must be skipped:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("module.exports={}")
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\x00\x00binary")

    files, truncated = collect_source_files(str(tmp_path), max_files=100)
    rels = {f.rel_path for f in files}

    assert "app/main.py" in rels
    assert "README.md" in rels
    assert not any("node_modules" in r for r in rels)
    assert "logo.png" not in rels
    assert truncated is False


def test_skips_lock_files_but_indexes_schema(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"x"}')          # kept (config)
    (tmp_path / "package-lock.json").write_text("{}")               # skipped (lock)
    (tmp_path / "package-lock-chaitanya.json").write_text("{}")     # skipped (*-lock.json)
    (tmp_path / "yarn.lock").write_text("...")                      # skipped (lock)
    (tmp_path / "schema.prisma").write_text("model User { id Int }")  # indexed (schema)

    files, _ = collect_source_files(str(tmp_path), max_files=100)
    rels = {f.rel_path for f in files}
    assert "package.json" in rels
    assert "schema.prisma" in rels
    assert "package-lock.json" not in rels
    assert "package-lock-chaitanya.json" not in rels
    assert "yarn.lock" not in rels


def test_truncation_flag_when_over_cap(tmp_path):
    for i in range(5):
        (tmp_path / f"m{i}.py").write_text("x=1")
    files, truncated = collect_source_files(str(tmp_path), max_files=2)
    assert len(files) == 2
    assert truncated is True
