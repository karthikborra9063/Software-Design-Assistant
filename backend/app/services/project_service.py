"""Project management: create (upload + enqueue), list, fetch, delete.

Upload returns immediately after saving the ZIP and enqueuing an index job — the heavy work
happens in the background worker. Every fetch/delete enforces ownership (project isolation).
"""

import os
import uuid

from werkzeug.utils import secure_filename

from ..config import Config
from ..errors import ApiError
from ..extensions import db
from ..models import JobType, Project, ProjectStatus
from . import queue as q


def create_project(user, name: str, file_storage) -> Project:
    """Validate the upload, persist the project + ZIP, enqueue indexing, return immediately."""
    name = (name or "").strip()
    if not name:
        raise ApiError("Project name is required.", 400)
    if file_storage is None or not (file_storage.filename or "").strip():
        raise ApiError("A .zip file is required.", 400)
    if not file_storage.filename.lower().endswith(".zip"):
        raise ApiError("Only .zip uploads are supported.", 400)

    project = Project(user_id=user.id, name=name, status=ProjectStatus.UPLOADING)
    db.session.add(project)
    db.session.commit()

    # Save the ZIP to a temp location for the worker. It is deleted after indexing —
    # we never persist the raw archive (HLD-v2 §7).
    os.makedirs(Config.UPLOAD_TMP, exist_ok=True)
    safe_name = secure_filename(file_storage.filename) or "upload.zip"
    zip_path = os.path.join(Config.UPLOAD_TMP, f"{project.id}_{uuid.uuid4().hex}_{safe_name}")
    file_storage.save(zip_path)

    project.status = ProjectStatus.INDEXING
    db.session.commit()
    q.enqueue(project.id, JobType.INDEX, {"zip_path": zip_path})
    return project


def list_projects(user) -> list[Project]:
    return (
        Project.query.filter_by(user_id=user.id)
        .order_by(Project.created_at.desc())
        .all()
    )


def get_owned_project(user, project_id: int) -> Project:
    """Fetch a project, enforcing that it belongs to the current user (404 otherwise)."""
    project = db.session.get(Project, project_id)
    if project is None or project.user_id != user.id:
        raise ApiError("Project not found.", 404)
    return project


def delete_project(user, project_id: int) -> None:
    project = get_owned_project(user, project_id)
    # Drop the project's PGVector collection (it lives in the vector store's own tables, so it
    # is not covered by the SQLAlchemy cascade). Best-effort — the DB row is the source of truth.
    try:
        from .vectorstore import get_vectorstore

        get_vectorstore(project_id).delete_collection()
    except Exception:
        pass
    db.session.delete(project)  # cascades chats / jobs
    db.session.commit()
