"""Flask extension singletons.

Created here *unbound* (no app yet) and attached to the app inside `create_app` via
`.init_app(app)`. This avoids circular imports and lets tests build isolated app instances.
"""

from flask_cors import CORS
from flask_jwt_extended import JWTManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()       # ORM / connection pool
migrate = Migrate()     # Alembic migrations (flask db ...)
jwt = JWTManager()      # JWT auth
cors = CORS()           # cross-origin access for the React frontend
