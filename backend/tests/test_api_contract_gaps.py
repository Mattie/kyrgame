import httpx
import pytest

from kyrgame.webapp import create_app


@pytest.mark.anyio
async def test_session_response_includes_expiration_metadata():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/session", json={"player_id": "gapcheck"})
            assert resp.status_code == 201
            session_data = resp.json()["session"]
            assert session_data["expires_at"].endswith("+00:00")
            assert session_data["expires_in_seconds"] > 23 * 60 * 60

            validate_resp = await client.get(
                "/auth/session",
                headers={"Authorization": f"Bearer {session_data['token']}"},
            )
            assert validate_resp.status_code == 200
            validate_data = validate_resp.json()["session"]
            assert validate_data["expires_at"] == session_data["expires_at"]
            assert validate_data["expires_in_seconds"] > 23 * 60 * 60

            resume_resp = await client.post(
                "/auth/session",
                json={"player_id": "gapcheck", "resume_token": session_data["token"]},
            )
            assert resume_resp.status_code == 200
            resume_data = resume_resp.json()["session"]
            assert resume_data["expires_at"] == session_data["expires_at"]
            assert resume_data["expires_in_seconds"] > 23 * 60 * 60
