from fastapi.testclient import TestClient

from claimos.main import app


def test_healthz_returns_200():
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_healthz_is_unauthenticated():
    """Healthcheck must be accessible without credentials."""
    client = TestClient(app)
    response = client.get("/healthz")
    assert response.status_code == 200
