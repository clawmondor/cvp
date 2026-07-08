"""Tests for user profile endpoints."""

import pytest
from fastapi.testclient import TestClient

from claimos.dependencies import CurrentUser, require_active_user


@pytest.fixture
def auth_client():
    from claimos.main import app

    async def mock_user():
        return CurrentUser(
            id="u1",
            email="test@test.com",
            system_role="internal_user",
            group_id="ig",
            group_kind="internal",
        )

    app.dependency_overrides[require_active_user] = mock_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_profile_page_accessible(auth_client):
    resp = auth_client.get("/profile")
    assert resp.status_code == 200
    assert "Password" in resp.text
