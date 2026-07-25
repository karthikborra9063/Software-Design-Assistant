"""Auth endpoints: register, login, and 'who am I'.

Register and login both return a JWT + the user object, so the frontend can log the user in
immediately after signup. Validation/hashing live in the auth service; this layer only handles
request/response shape.
"""

from flask import Blueprint, jsonify, request
from flask_jwt_extended import create_access_token, jwt_required

from ..services.auth_service import authenticate_user, register_user
from .deps import current_user

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _token_response(user):
    # JWT 'sub' must be a string; we cast the id and cast back in current_user().
    token = create_access_token(identity=str(user.id))
    return {"access_token": token, "user": user.to_dict()}


@auth_bp.post("/register")
def register():
    data = request.get_json(silent=True) or {}
    user = register_user(data.get("name"), data.get("email"), data.get("password"))
    return jsonify(_token_response(user)), 201


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    user = authenticate_user(data.get("email"), data.get("password"))
    return jsonify(_token_response(user))


@auth_bp.get("/me")
@jwt_required()
def me():
    """Validate the token and return the current user (used by the frontend on load)."""
    return jsonify({"user": current_user().to_dict()})
