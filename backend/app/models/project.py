"""Project (one uploaded codebase) and its lifecycle status."""

from sqlalchemy.dialects.postgresql import JSONB

from ..extensions import db


class ProjectStatus:
    """Indexing lifecycle, surfaced to the user (HLD-v2 §3)."""

    UPLOADING = "UPLOADING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=ProjectStatus.UPLOADING)

    # Indexing stats (shown in the dashboard).
    language = db.Column(db.String(50))
    total_files = db.Column(db.Integer, default=0)
    total_chunks = db.Column(db.Integer, default=0)
    failure_reason = db.Column(db.Text)  # populated when status == FAILED

    # Structural artifacts fetched wholesale by project_id (NOT embedded — see HLD-v2 §2.3):
    #   context_card: compact overview (file tree + README summary + entrypoints/frameworks)
    #   repo_map:     full per-file signature skeletons (used by the escalation hop)
    context_card = db.Column(JSONB)
    repo_map = db.Column(JSONB)

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    indexed_at = db.Column(db.DateTime)

    user = db.relationship("User", back_populates="projects")
    # All children cascade-delete with the project. (Chunk vectors live in PGVector's own
    # per-project collection — see services/vectorstore.py — not in a SQLAlchemy table.)
    chats = db.relationship("Chat", back_populates="project", cascade="all, delete-orphan")
    jobs = db.relationship("Job", back_populates="project", cascade="all, delete-orphan")

    def to_dict(self) -> dict:
        """Public representation (excludes the large context_card/repo_map blobs)."""
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "language": self.language,
            "total_files": self.total_files,
            "total_chunks": self.total_chunks,
            "failure_reason": self.failure_reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
        }

    def __repr__(self) -> str:
        return f"<Project {self.id} {self.name} [{self.status}]>"
