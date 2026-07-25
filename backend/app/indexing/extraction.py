"""Safe ZIP extraction (HLD-v2 §4).

Guards against the two classic archive attacks/failures:
- Path traversal ("../../etc/..."): every entry must resolve inside the destination dir.
- Zip bombs: caps on file count and total uncompressed size before writing anything.
"""

import os
import shutil
import zipfile

from ..config import Config
from ..errors import PermanentJobError
from .files import is_in_skipped_dir


def _safe_target(dest_dir: str, member_name: str) -> str | None:
    """Resolve an archive member to an absolute path INSIDE dest_dir, or None if it escapes."""
    dest_abs = os.path.abspath(dest_dir)
    target = os.path.abspath(os.path.join(dest_abs, member_name))
    if target == dest_abs or target.startswith(dest_abs + os.sep):
        return target
    return None


def extract_archive(
    zip_path: str,
    dest_dir: str,
    max_entries: int | None = None,
    max_uncompressed_bytes: int | None = None,
) -> None:
    """Extract `zip_path` into `dest_dir`, enforcing the safety limits. Raises PermanentJobError.

    Caps default to the (env-configurable) Config values; pass explicit values in tests.
    Note: this only bounds total *archive* size/entries (bomb/DoS guards). The cap on how many
    files we actually index is applied afterwards, during the file walk, with truncation — so a
    large repo full of vendored files is accepted and simply has that noise skipped.
    """
    max_entries = max_entries or Config.MAX_ARCHIVE_ENTRIES
    max_uncompressed_bytes = max_uncompressed_bytes or Config.MAX_UNCOMPRESSED_BYTES

    if not zipfile.is_zipfile(zip_path):
        raise PermanentJobError("Uploaded file is not a valid ZIP archive.")

    with zipfile.ZipFile(zip_path) as zf:
        all_files = [i for i in zf.infolist() if not i.is_dir()]
        if not all_files:
            raise PermanentJobError("The ZIP archive is empty.")

        # Filter FIRST: drop vendored/build/VCS files (node_modules, .git, dist, …). These are
        # never indexed, so they must not be extracted or counted against the caps.
        kept = [i for i in all_files if not is_in_skipped_dir(i.filename)]
        if not kept:
            raise PermanentJobError(
                "No indexable files found (the archive appears to contain only "
                "dependencies/build output)."
            )

        # Caps apply to the KEPT (relevant) files only.
        if len(kept) > max_entries:
            raise PermanentJobError(
                f"Archive has {len(kept)} indexable files (limit {max_entries}). "
                "This project is unusually large; consider splitting it."
            )
        if sum(i.file_size for i in kept) > max_uncompressed_bytes:
            raise PermanentJobError("Archive is too large when uncompressed.")

        for info in kept:
            target = _safe_target(dest_dir, info.filename)
            if target is None:
                raise PermanentJobError("Archive contains an unsafe (path-traversal) entry.")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
