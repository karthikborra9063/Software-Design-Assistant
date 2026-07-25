"""Health-check endpoint.

Used by Render to confirm the service is up, and as the first thing to hit when verifying the
scaffold. Intentionally trivial and unauthenticated.
"""

from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)


@health_bp.get("/api/health")
def health():
    return jsonify({"status": "ok", "service": "aira-backend"})
