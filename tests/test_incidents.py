import pytest
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.main import app

AUTH_HEADERS = {"X-API-Key": settings.api_key}


@pytest.mark.asyncio
async def test_create_and_get_incident():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        create_resp = await ac.post("/incidents", json={"title": "Broker timeout spike", "severity": "sev2"}, headers=AUTH_HEADERS)
        assert create_resp.status_code == 201
        incident_id = create_resp.json()["id"]

        get_resp = await ac.get(f"/incidents/{incident_id}", headers=AUTH_HEADERS)
        assert get_resp.status_code == 200
        assert get_resp.json()["title"] == "Broker timeout spike"


@pytest.mark.asyncio
async def test_get_missing_incident_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/incidents/does-not-exist", headers=AUTH_HEADERS)
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_review_missing_incident_404():
    # Fast, no-LLM check -- the full generation path (real LLM call, ~60s+)
    # is verified live/manually, not in the unit suite.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/incidents/does-not-exist/review", json={}, headers=AUTH_HEADERS)
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_incidents_requires_api_key():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.get("/incidents")
        assert resp.status_code in (401, 422)  # 422 if header missing entirely, 401 if wrong


@pytest.mark.asyncio
async def test_health_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        assert (await ac.get("/healthz")).status_code == 200
        assert (await ac.get("/readyz")).status_code == 200
