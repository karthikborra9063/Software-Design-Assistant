"""Background job — the Postgres-as-queue row (HLD-v2 §7).

The worker loop claims PENDING rows with `FOR UPDATE SKIP LOCKED`, so this table *is* the
queue — no Redis. `attempts` drives retry; a boot-recovery sweep resets stale RUNNING rows
(killed by a restart) back to PENDING.
"""

from sqlalchemy.dialects.postgresql import JSONB

from ..extensions import db


class JobStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class JobType:
    INDEX = "index"  # parse + chunk + embed + build repo map


class Job(db.Model):
    __tablename__ = "jobs"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(
        db.Integer, db.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type = db.Column(db.String(30), nullable=False, default=JobType.INDEX)
    status = db.Column(db.String(20), nullable=False, default=JobStatus.PENDING)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    error = db.Column(db.Text)
    payload = db.Column(JSONB)  # e.g. path to the extracted upload

    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    started_at = db.Column(db.DateTime)
    finished_at = db.Column(db.DateTime)

    project = db.relationship("Project", back_populates="jobs")

    __table_args__ = (
        # The queue poller orders by (status, created_at); index it.
        db.Index("ix_jobs_status_created", "status", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Job {self.id} {self.type} [{self.status}]>"
