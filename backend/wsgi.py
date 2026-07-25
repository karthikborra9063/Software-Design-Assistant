"""WSGI entrypoint — the SERVER process.

- Production (Render): `gunicorn wsgi:app` imports `app` below.
- Local: `python wsgi.py` runs Flask's dev server on port 5000.

The background worker is started HERE (not in create_app) so that `flask` CLI commands
(e.g. `flask init-db`, run with FLASK_APP=app) and tests never spawn it. Set RUN_WORKER=0 to
disable it in a given process.
"""

import os

from app import create_app
from app.worker import start_worker

app = create_app()
start_worker(app)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=not app.config["IS_PRODUCTION"],
        use_reloader=False,  # avoid a second process (and second worker) under the dev server
    )
