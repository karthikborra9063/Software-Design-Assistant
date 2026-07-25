"""App smoke tests (no DB needed): health check + auth guard on protected routes."""


def test_health_ok(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_projects_requires_auth(client):
    # No JWT -> 401 before any DB access.
    r = client.get("/api/projects")
    assert r.status_code == 401


def test_unknown_route_returns_json_404(client):
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404
    assert "error" in r.get_json()
