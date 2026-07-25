"""Chat / Q&A endpoints (all require auth + project ownership).

- POST /api/projects/<id>/ask          blocking JSON answer (+ citations + meta)
- POST /api/projects/<id>/ask/stream   Server-Sent Events: meta → token* → done
- GET  /api/projects/<id>/chats         chat history for the project

The `validate_ask` guard runs BEFORE streaming so bad requests (project not ready, empty
question) return a normal HTTP error rather than an SSE error frame.
"""

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask_jwt_extended import jwt_required

from ..models import Chat
from ..services import project_service as ps
from ..services import qa_service as qa
from .deps import current_user

chat_bp = Blueprint("chat", __name__, url_prefix="/api/projects")


def _question_from_request() -> str:
    data = request.get_json(silent=True) or {}
    return (data.get("question") or "").strip()


@chat_bp.post("/<int:project_id>/ask")
@jwt_required()
def ask(project_id: int):
    user = current_user()
    project = ps.get_owned_project(user, project_id)
    question = _question_from_request()
    qa.validate_ask(project, question)
    return jsonify(qa.answer(user, project, question))


@chat_bp.post("/<int:project_id>/ask/stream")
@jwt_required()
def ask_stream(project_id: int):
    user = current_user()
    project = ps.get_owned_project(user, project_id)
    question = _question_from_request()
    qa.validate_ask(project, question)  # raises -> normal JSON error before streaming starts

    generator = qa.answer_stream(user, project, question)
    return Response(
        stream_with_context(generator),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering so tokens flush immediately
            "Connection": "keep-alive",
        },
    )


@chat_bp.get("/<int:project_id>/chats")
@jwt_required()
def history(project_id: int):
    user = current_user()
    ps.get_owned_project(user, project_id)  # ownership check (404 if not the user's)
    chats = (
        Chat.query.filter_by(project_id=project_id, user_id=user.id)
        .order_by(Chat.created_at.asc())
        .all()
    )
    return jsonify({"chats": [c.to_dict() for c in chats]})
