"""In-process background worker.

`WORKER_CONCURRENCY` daemon threads poll the Postgres-as-queue and run indexing jobs. Started
once per process from `wsgi.py` (not from create_app, so `flask` CLI commands and tests don't
spawn them). Job claiming uses `FOR UPDATE SKIP LOCKED`, so multiple threads/processes never
process the same job.
"""

import os
import threading
import time

from .errors import PermanentJobError
from .extensions import db
from .models import Project, ProjectStatus
from .services import queue as q
from .services.indexing_service import index_project

POLL_INTERVAL_SECONDS = 2.0
_started = False  # guard: at most one worker thread per process


def start_worker(app) -> None:
    global _started
    if _started or app.config.get("TESTING") or os.environ.get("RUN_WORKER", "1") == "0":
        return
    _started = True

    # Boot-recovery runs ONCE (before any poller starts) so half-finished jobs from a previous
    # process are requeued exactly one time.
    with app.app_context():
        _safe(app, q.recover_stale_jobs, "boot-recovery sweep")

    concurrency = max(1, int(app.config.get("WORKER_CONCURRENCY", 1)))
    for i in range(concurrency):
        threading.Thread(
            target=_poll_loop, args=(app,), daemon=True, name=f"aira-worker-{i}"
        ).start()
    app.logger.info("Background worker started (%d thread(s)).", concurrency)


def _poll_loop(app) -> None:
    # A long-lived app context per thread; DB session is committed per unit of work.
    # Concurrent threads are safe: claim_next_job() uses FOR UPDATE SKIP LOCKED.
    with app.app_context():
        while True:
            try:
                job = q.claim_next_job()
                if job is None:
                    db.session.remove()  # release the connection between polls
                    time.sleep(POLL_INTERVAL_SECONDS)
                    continue
                _process(app, job)
            except Exception:  # never let the loop die
                app.logger.exception("Worker loop error")
                db.session.rollback()
                time.sleep(POLL_INTERVAL_SECONDS)


def _process(app, job) -> None:
    project_id = job.project_id
    payload = job.payload or {}
    try:
        index_project(project_id, payload)
        q.complete_job(job)
        _cleanup(payload)
    except Exception as e:
        permanent = isinstance(e, PermanentJobError)
        app.logger.exception("Job %s failed (attempt %s, permanent=%s)", job.id, job.attempts, permanent)
        db.session.rollback()  # discard the failed unit's partial state before writing job status
        failed_for_good = q.fail_job(job, str(e), permanent=permanent)
        if failed_for_good:
            _mark_project_failed(project_id, str(e))
            _cleanup(payload)


def _mark_project_failed(project_id: int, reason: str) -> None:
    project = db.session.get(Project, project_id)
    if project is not None:
        project.status = ProjectStatus.FAILED
        project.failure_reason = (reason or "Indexing failed.")[:1000]
        db.session.commit()


def _cleanup(payload: dict) -> None:
    """Delete the temp upload — we never persist the raw ZIP (HLD-v2 §7)."""
    zip_path = (payload or {}).get("zip_path")
    if zip_path and os.path.exists(zip_path):
        try:
            os.remove(zip_path)
        except OSError:
            pass


def _safe(app, fn, label: str) -> None:
    try:
        fn()
    except Exception:
        app.logger.exception("Worker %s failed", label)
        db.session.rollback()
