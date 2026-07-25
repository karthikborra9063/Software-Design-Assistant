"""Custom Flask CLI commands.

`flask init-db` is the one-command setup: it enables the pgvector extension, then creates all
tables (with the vector column sized to the current EMBED_DIM). Run once per database — i.e.
once for your local Neon dev branch, and once for the Render/Neon prod database.

(Flask-Migrate/Alembic is also wired for schema evolution later, but for this project a single
create_all is simpler and sufficient — see README.)
"""

import click
from sqlalchemy import text

from .extensions import db


def register_cli(app) -> None:
    @app.cli.command("init-db")
    def init_db() -> None:
        """Enable pgvector and create the application tables."""
        # PGVector needs the extension before it creates its own embedding tables (lazily, on
        # first index). Our app tables (users/projects/chats/jobs) are created here.
        db.session.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        db.session.commit()
        db.create_all()
        dim = app.config["EMBED_DIM"]
        click.echo(f"Initialized database: pgvector enabled, tables created (vector dim={dim}).")
