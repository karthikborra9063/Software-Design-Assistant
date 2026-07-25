"""Safe-extraction failure paths (HLD-v2 §4)."""

import zipfile

import pytest

from app.errors import PermanentJobError
from app.indexing.extraction import extract_archive


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def test_extracts_a_normal_archive(tmp_path):
    zip_path = tmp_path / "ok.zip"
    _make_zip(zip_path, {"src/main.py": "print(1)", "README.md": "# hi"})
    dest = tmp_path / "out"
    dest.mkdir()
    extract_archive(str(zip_path), str(dest))
    assert (dest / "src" / "main.py").exists()


def test_rejects_path_traversal(tmp_path):
    zip_path = tmp_path / "evil.zip"
    _make_zip(zip_path, {"../escape.txt": "pwn"})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(PermanentJobError):
        extract_archive(str(zip_path), str(dest))


def test_rejects_too_many_entries(tmp_path):
    zip_path = tmp_path / "many.zip"
    _make_zip(zip_path, {f"f{i}.py": "x" for i in range(5)})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(PermanentJobError):
        extract_archive(str(zip_path), str(dest), max_entries=2)


def test_vendored_entries_are_skipped_not_counted(tmp_path):
    # 10 node_modules files + 2 real files; a cap of 5 must PASS because only the 2 real
    # files count — and node_modules must not be extracted.
    entries = {f"node_modules/dep{i}/index.js": "x" for i in range(10)}
    entries[".git/config"] = "gitdata"
    entries["src/app.py"] = "print(1)"
    entries["README.md"] = "# hi"
    zip_path = tmp_path / "withdeps.zip"
    _make_zip(zip_path, entries)
    dest = tmp_path / "out"
    dest.mkdir()
    extract_archive(str(zip_path), str(dest), max_entries=5)
    assert (dest / "src" / "app.py").exists()
    assert not (dest / "node_modules").exists()
    assert not (dest / ".git").exists()


def test_rejects_empty_archive(tmp_path):
    zip_path = tmp_path / "empty.zip"
    _make_zip(zip_path, {})
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(PermanentJobError):
        extract_archive(str(zip_path), str(dest))


def test_rejects_non_zip(tmp_path):
    fake = tmp_path / "not.zip"
    fake.write_text("this is not a zip")
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(PermanentJobError):
        extract_archive(str(fake), str(dest))
