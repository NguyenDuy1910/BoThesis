from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from api.routers import PasswordSessionCreate
from api.routers.auth import _session_response
from bothesis.services import AuthenticationSession


def test_session_response_includes_bearer_token_type() -> None:
    result = AuthenticationSession(
        access_token="test-token",
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        session_id=uuid4(),
        user_id=uuid4(),
        email="admin@example.com",
        display_name="Admin",
        active_tenant_id=uuid4(),
        permissions=("tenant.read",),
        tenants=(),
    )

    response = _session_response(result)

    assert response.token_type == "bearer"


def test_password_session_accepts_username_or_email_but_not_both() -> None:
    username_request = PasswordSessionCreate(
        method="password", username="analyst", password="correct horse battery staple"
    )
    email_request = PasswordSessionCreate(
        method="password", email="analyst@example.com", password="correct horse battery staple"
    )

    assert username_request.username == "analyst"
    assert email_request.email == "analyst@example.com"
    with pytest.raises(ValueError, match="exactly one"):
        PasswordSessionCreate(
            method="password",
            email="analyst@example.com",
            username="analyst",
            password="correct horse battery staple",
        )
