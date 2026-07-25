"""Postgres-as-queue (HLD-v2 §7) — durable background jobs with no Redis.

The `jobs` table IS the queue. A worker claims the oldest PENDING row using
`FOR UPDATE SKIP LOCKED`, so multiple pollers (threads/processes) never grab the same job.
Retries are bounded by MAX_ATTEMPTS; a boot-recovery sweep resets rows left RUNNING by a
crashed/slept process back to PENDING.
"""

from datetime import datetime, timedelta

from ..extensions import db
from ..models import Job, JobStatus

MAX_ATTEMPTS = 3
STALE_MINUTES = 10  # a RUNNING job older than this is assumed dead (crash/restart)


def enqueue(project_id: int, job_type: str, payload: dict | None = None) -> Job:
    job = Job(project_id=project_id, type=job_type, payload=payload or {}, status=JobStatus.PENDING)
    db.session.add(job)
    db.session.commit()
    return job


def claim_next_job() -> Job | None:
    """Atomically claim the oldest PENDING job. Returns None if the queue is empty.

    `with_for_update(skip_locked=True)` locks the selected row and skips rows already locked by
    other workers, so concurrent pollers are safe. Flipping status to RUNNING + committing
    releases the lock and makes the claim visible.
    """
    job = (
        db.session.query(Job)
        .filter(Job.status == JobStatus.PENDING)
        .order_by(Job.created_at.asc())
        .with_for_update(skip_locked=True)
        .first()
    )
    if job is None:
        db.session.commit()  # close the (empty) transaction / release the connection
        return None

    job.status = JobStatus.RUNNING
    job.started_at = datetime.utcnow()
    job.attempts += 1
    db.session.commit()
    return job


def complete_job(job: Job) -> None:
    job.status = JobStatus.DONE
    job.finished_at = datetime.utcnow()
    db.session.commit()


def fail_job(job: Job, error: str, permanent: bool = False) -> bool:
    """Record a failure. Returns True if the job is now permanently FAILED.

    Permanent errors (or attempts exhausted) -> FAILED. Otherwise -> back to PENDING for retry.
    """
    job.error = (error or "")[:2000]
    if permanent or job.attempts >= MAX_ATTEMPTS:
        job.status = JobStatus.FAILED
        job.finished_at = datetime.utcnow()
        db.session.commit()
        return True
    job.status = JobStatus.PENDING  # requeue for another attempt
    db.session.commit()
    return False


def recover_stale_jobs() -> int:
    """Boot recovery: reset RUNNING jobs older than STALE_MINUTES back to PENDING.

    These are jobs whose worker died mid-run (restart/idle-sleep). Returns the count reset.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=STALE_MINUTES)
    n = (
        db.session.query(Job)
        .filter(Job.status == JobStatus.RUNNING, Job.started_at < cutoff)
        .update({Job.status: JobStatus.PENDING}, synchronize_session=False)
    )
    db.session.commit()
    return n
