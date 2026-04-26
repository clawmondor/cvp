"""Tests for security headers middleware."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cvp.middleware import SecurityHeadersMiddleware


def _make_app(environment: str = "production") -> FastAPI:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, environment=environment)

    @app.get("/test")
    def test_endpoint():
        return {"ok": True}

    return app


def test_security_headers_present():
    client = TestClient(_make_app())
    resp = client.get("/test")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "x-request-id" in resp.headers
    assert "content-security-policy" in resp.headers
    assert "permissions-policy" in resp.headers


def test_hsts_only_in_production():
    client = TestClient(_make_app("production"))
    resp = client.get("/test")
    assert "strict-transport-security" in resp.headers

    client_dev = TestClient(_make_app("dev"))
    resp_dev = client_dev.get("/test")
    assert "strict-transport-security" not in resp_dev.headers
