from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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
