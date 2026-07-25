"""Indexing orchestrator (HLD-v2 §3).

Full pipeline, run by the background worker:
  extract (safe) -> walk/classify files -> chunk (Tree-sitter + fallback) -> embed (batched)
  -> store chunks in pgvector -> build repo map/context card -> mark project READY.

Re-indexing is idempotent: existing chunks for the project are cleared first. Transient errors
(e.g. embedding API hiccups) propagate as plain exceptions so the worker retries; bad input
raises PermanentJobError so it fails fast. Temp files are always cleaned up.
"""

import logging
import shutil
import tempfile
from datetime import datetime

log = logging.getLogger("aira.indexing")

from langchain_core.documents import Document

from ..config import Config
from ..errors import PermanentJobError
from ..extensions import db
from ..indexing.chunking import chunk_file
from ..indexing.extraction import extract_archive
from ..indexing.files import collect_source_files, read_text
from ..indexing.repo_map import build_repo_map
from ..models import Project, ProjectStatus
from .vectorstore import get_vectorstore

_ADD_BATCH = 500  # docs embedded + written to PGVector per batch (bounds peak memory)


def index_project(project_id: int, payload: dict) -> None:
    project = db.session.get(Project, project_id)
    if project is None:  # deleted before the job ran
        return

    project.status = ProjectStatus.INDEXING
    db.session.commit()

    zip_path = (payload or {}).get("zip_path")
    if not zip_path:
        raise PermanentJobError("Uploaded archive not found.")

    workdir = tempfile.mkdtemp(prefix=f"aira_idx_{project_id}_")
    try:
        # 1. Safe extraction (raises PermanentJobError on bad/oversized/unsafe archives).
        extract_archive(zip_path, workdir)

        # 2. Discover + classify files.
        files, truncated = collect_source_files(workdir, Config.MAX_REPO_FILES)
        if not files:
            raise PermanentJobError("No indexable source files found in the archive.")
        if truncated:
            # Never silently truncate (HLD-v2 §2/§4): surface that we capped the file set.
            log.warning(
                "Project %s exceeded the %s-file cap; indexing a bounded subset.",
                project_id, Config.MAX_REPO_FILES,
            )

        # 3. Chunk every file (never drops a file — falls back to line windows).
        all_chunks: list[dict] = []
        for sf in files:
            text = read_text(sf.abs_path)
            if text is None:
                continue
            all_chunks.extend(chunk_file(text, sf.category, sf.language, sf.rel_path))
        if not all_chunks:
            raise PermanentJobError("No readable content could be extracted from the archive.")

        # 4 + 5. Embed and store into the project's PGVector collection, in batches so peak
        # memory stays bounded to a single batch of vectors (important on a small prod
        # instance). Opening the store with pre_delete=True drops any previous collection first,
        # so re-indexing is idempotent. add_documents embeds each batch via our throttled client.
        store = get_vectorstore(project_id, pre_delete=True)
        for start in range(0, len(all_chunks), _ADD_BATCH):
            batch = all_chunks[start : start + _ADD_BATCH]
            store.add_documents(
                [
                    Document(
                        page_content=c["content"],
                        metadata={
                            "project_id": project_id,
                            "file_path": c["file_path"],
                            "language": c["language"],
                            "chunk_type": c["chunk_type"],
                            "symbol_name": c["symbol_name"],
                            "start_line": c["start_line"],
                            "end_line": c["end_line"],
                        },
                    )
                    for c in batch
                ]
            )

        # 6. Repo map + context card (zero LLM).
        context_card, repo_map, language = build_repo_map(files, all_chunks)

        # 7. Finalize.
        project.context_card = context_card
        project.repo_map = repo_map
        project.language = language
        project.total_files = len(files)
        project.total_chunks = len(all_chunks)
        project.status = ProjectStatus.READY
        project.indexed_at = datetime.utcnow()
        project.failure_reason = None
        db.session.commit()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
