import httpx
import pytest

from kyrgame.webapp import create_app


@pytest.mark.anyio
@pytest.mark.xfail(reason="Session expiration metadata is not yet exposed by the HTTP API")
async def test_session_response_includes_expiration_metadata():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/session", json={"player_id": "gapcheck"})
            assert resp.status_code == 201
            session_data = resp.json()["session"]
            assert "expires_at" in session_data
            assert session_data["expires_at"]
