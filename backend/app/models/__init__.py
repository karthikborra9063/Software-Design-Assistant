"""SQLAlchemy models package.

Importing this module registers every table on `db.metadata`, which is what the factory's
`from . import models` relies on (so `db.create_all()` / migrations see them all).
"""

from .chat import Chat
from .job import Job, JobStatus, JobType
from .project import Project, ProjectStatus
from .user import User

__all__ = [
    "Chat",
    "Job",
    "JobStatus",
    "JobType",
    "Project",
    "ProjectStatus",
    "User",
]
