"""Authentication logic: validation, password hashing, credential checks.

Passwords are stored only as pbkdf2:sha256 hashes (never plaintext). pbkdf2 is chosen over
the newer scrypt default for portability — it has no OpenSSL/memory requirements that can
fail on constrained hosts.
"""

import re

from werkzeug.security import check_password_hash, generate_password_hash

from ..errors import ApiError
from ..extensions import db
from ..models import User

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_PASSWORD_LEN = 8


def register_user(name: str, email: str, password: str) -> User:
    """Validate input, ensure the email is unique, create and persist the user."""
    name = (name or "").strip()
    email = (email or "").strip().lower()

    if not name:
        raise ApiError("Name is required.", 400)
    if not _EMAIL_RE.match(email):
        raise ApiError("A valid email is required.", 400)
    if not password or len(password) < _MIN_PASSWORD_LEN:
        raise ApiError(f"Password must be at least {_MIN_PASSWORD_LEN} characters.", 400)

    if User.query.filter_by(email=email).first():
        raise ApiError("An account with this email already exists.", 409)

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password, method="pbkdf2:sha256"),
    )
    db.session.add(user)
    db.session.commit()
    return user


def authenticate_user(email: str, password: str) -> User:
    """Return the user for valid credentials, else raise 401.

    The same error is used for unknown email and wrong password so we don't leak which
    emails are registered.
    """
    email = (email or "").strip().lower()
    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password_hash, password or ""):
        raise ApiError("Invalid email or password.", 401)
    return user
