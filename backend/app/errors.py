"""Consistent JSON error handling for the whole API.

Raise `ApiError("message", status)` anywhere in the request path and the client gets a clean
`{"error": "..."}` body with the right HTTP status. Also maps a few framework errors
(oversized upload, 404, 405) to the same JSON shape. Unhandled exceptions are left alone so the
dev debugger / real 500s still surface.
"""

from flask import jsonify


class ApiError(Exception):
    """An expected, client-facing error (bad input, auth failure, conflict, ...)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


class PermanentJobError(Exception):
    """A background-job failure that retrying cannot fix (e.g. corrupt ZIP).

    The worker marks the job FAILED immediately instead of retrying. Transient errors
    (network, rate limits) raise a plain Exception and are retried.
    """



def register_error_handlers(app) -> None:
    @app.errorhandler(ApiError)
    def _handle_api_error(e: ApiError):
        return jsonify({"error": e.message}), e.status

    @app.errorhandler(413)
    def _handle_too_large(_e):
        return (
            jsonify({"error": f"Upload exceeds the {app.config['MAX_UPLOAD_MB']} MB limit."}),
            413,
        )

    @app.errorhandler(404)
    def _handle_404(_e):
        return jsonify({"error": "Not found."}), 404

    @app.errorhandler(405)
    def _handle_405(_e):
        return jsonify({"error": "Method not allowed."}), 405
