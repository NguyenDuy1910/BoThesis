from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import main
from bothesis.health import HealthService, HealthSettings

SETTINGS = HealthSettings(
    qdrant_url="https://qdrant.example",
    qdrant_api_key="qdrant-secret",
    qdrant_collection="bothesis",
    openrouter_base_url="https://openrouter.example/api/v1",
    openrouter_api_key="openrouter-secret",
    chat_model="openai/gpt-5.4-mini",
    embedding_model="openai/text-embedding-3-small",
    langfuse_base_url="https://langfuse.example",
    langfuse_public_key="langfuse-public",
    langfuse_secret_key="langfuse-secret",
)


def _service(handler) -> HealthService:
    return HealthService(
        SETTINGS,
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )


def _get_health(service: HealthService) -> httpx.Response:
    main.app.dependency_overrides[main._get_health_service] = lambda: service
    try:
        with TestClient(main.app) as client:
            return client.get("/health")
    finally:
        main.app.dependency_overrides.pop(main._get_health_service, None)


def test_health_reports_all_configured_services_as_healthy() -> None:
    openrouter_paths: set[str] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "qdrant.example":
            assert request.headers["api-key"] == "qdrant-secret"
            return httpx.Response(200, json={"result": {"status": "green"}})
        if request.url.host == "openrouter.example":
            openrouter_paths.add(request.url.path)
            assert request.headers["authorization"] == "Bearer openrouter-secret"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "openai/gpt-5.4-mini"},
                        {"id": "openai/text-embedding-3-small"},
                    ]
                },
            )
        assert request.url.host == "langfuse.example"
        assert request.headers["authorization"].startswith("Basic ")
        return httpx.Response(200, json={"data": [{"id": "project-1"}]})

    response = _get_health(_service(handler))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"
    assert {service["name"] for service in payload["services"]} == {
        "api",
        "qdrant",
        "openrouter_chat",
        "openrouter_embeddings",
        "langfuse",
    }
    assert all(service["status"] == "healthy" for service in payload["services"])
    assert (
        next(service for service in payload["services"] if service["name"] == "qdrant")[
            "collection"
        ]
        == "bothesis"
    )
    assert openrouter_paths == {
        "/api/v1/models",
        "/api/v1/embeddings/models",
    }


def test_health_returns_503_when_required_services_are_unhealthy() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "qdrant.example":
            return httpx.Response(503)
        if request.url.host == "openrouter.example":
            return httpx.Response(401)
        return httpx.Response(200, json={"data": [{"id": "project-1"}]})

    response = _get_health(_service(handler))

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "unhealthy"
    services = {service["name"]: service for service in payload["services"]}
    assert services["qdrant"]["error_category"] == "upstream_error"
    assert services["openrouter_chat"]["error_category"] == ("authentication_failed")
    serialized = json.dumps(payload)
    assert "qdrant-secret" not in serialized
    assert "openrouter-secret" not in serialized
    assert "langfuse-secret" not in serialized
    assert "https://" not in serialized


def test_health_is_degraded_when_optional_langfuse_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "qdrant.example":
            return httpx.Response(200, json={"result": {}})
        if request.url.host == "openrouter.example":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": SETTINGS.chat_model},
                        {"id": SETTINGS.embedding_model},
                    ]
                },
            )
        return httpx.Response(503)

    response = _get_health(_service(handler))

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "degraded"
    langfuse = next(
        service for service in payload["services"] if service["name"] == "langfuse"
    )
    assert langfuse["required"] is False
    assert langfuse["status"] == "unhealthy"


def test_unconfigured_optional_langfuse_does_not_fail_readiness() -> None:
    settings = replace(
        SETTINGS,
        langfuse_public_key=None,
        langfuse_secret_key=None,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "qdrant.example":
            return httpx.Response(200, json={"result": {}})
        assert request.url.host == "openrouter.example"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": SETTINGS.chat_model},
                    {"id": SETTINGS.embedding_model},
                ]
            },
        )

    response = _get_health(
        HealthService(
            settings,
            timeout_seconds=1,
            transport=httpx.MockTransport(handler),
        )
    )

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"
    langfuse = next(
        service
        for service in response.json()["services"]
        if service["name"] == "langfuse"
    )
    assert langfuse["status"] == "not_configured"
