"""Shared request-scoped helpers for the API layer."""

from flask_jwt_extended import get_jwt_identity

from ..errors import ApiError
from ..extensions import db
from ..models import User


def current_user() -> User:
    """Resolve the authenticated user from the JWT.

    The JWT identity is stored as a string (`str(user.id)`); we cast it back and load the row.
    Raises 401 if the token's user no longer exists. Call only inside `@jwt_required()` routes.
    """
    user = db.session.get(User, int(get_jwt_identity()))
    if user is None:
        raise ApiError("User not found.", 401)
    return user
