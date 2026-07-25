"""User account."""

from ..extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)  # werkzeug hash, never plaintext
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)

    # Deleting a user removes all their projects (and, via cascade, everything under them).
    projects = db.relationship(
        "Project", back_populates="user", cascade="all, delete-orphan"
    )

    def to_dict(self) -> dict:
        """Public representation — NEVER includes password_hash."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<User {self.id} {self.email}>"
