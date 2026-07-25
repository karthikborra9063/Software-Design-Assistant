"""Project endpoints (all require auth; all enforce ownership via the service layer).

- POST   /api/projects            multipart upload (name + file) -> 202, returns the project
- GET    /api/projects            list the user's projects
- GET    /api/projects/<id>       fetch one (frontend polls this for indexing status)
- DELETE /api/projects/<id>       delete a project and everything under it
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from ..services import project_service as ps
from .deps import current_user

projects_bp = Blueprint("projects", __name__, url_prefix="/api/projects")


@projects_bp.post("")
@jwt_required()
def create():
    user = current_user()
    project = ps.create_project(user, request.form.get("name"), request.files.get("file"))
    # 202 Accepted: the project exists and indexing is queued, but not finished yet.
    return jsonify({"project": project.to_dict()}), 202


@projects_bp.get("")
@jwt_required()
def list_projects():
    user = current_user()
    return jsonify({"projects": [p.to_dict() for p in ps.list_projects(user)]})


@projects_bp.get("/<int:project_id>")
@jwt_required()
def get_project(project_id: int):
    user = current_user()
    return jsonify({"project": ps.get_owned_project(user, project_id).to_dict()})


@projects_bp.delete("/<int:project_id>")
@jwt_required()
def delete_project(project_id: int):
    user = current_user()
    ps.delete_project(user, project_id)
    return jsonify({"status": "deleted", "id": project_id})
