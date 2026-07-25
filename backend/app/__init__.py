"""Application factory.

`create_app()` builds and configures a Flask app. Using a factory (instead of a module-level
`app`) lets us create fresh, independently-configured instances for tests and for gunicorn
workers in production.
"""

from flask import Flask

from .config import Config
from .extensions import cors, db, jwt, migrate


def create_app(config_class: type = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Bind extensions to this app instance.
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    # CORS origin comes from config: "*" locally, the deployed frontend URL in production.
    cors.init_app(
        app, resources={r"/api/*": {"origins": app.config["FRONTEND_ORIGIN"]}}
    )

    # Import models so table metadata is registered (create_all / migrations see them).
    from . import models  # noqa: F401  (imported for its table-registration side effect)

    # Consistent JSON error responses across the API.
    from .errors import register_error_handlers

    register_error_handlers(app)

    # Register HTTP blueprints.
    from .api.auth import auth_bp
    from .api.chat import chat_bp
    from .api.health import health_bp
    from .api.projects import projects_bp

    app.register_blueprint(health_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(projects_bp)
    app.register_blueprint(chat_bp)

    # Custom CLI commands (e.g. `flask init-db`).
    from .cli import register_cli

    register_cli(app)

    return app
