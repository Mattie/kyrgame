import httpx
import pytest

from kyrgame.webapp import create_app


@pytest.mark.anyio
async def test_content_lookup_returns_message_texts_from_catalog():
    app = create_app()
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            location = await client.get(
                "/content/lookup", params={"type": "location", "id": 38}
            )
            assert location.status_code == 200
            payload = location.json()
            assert payload["message_id"] == "KRD038"
            assert "Fountain" in payload["text"]

            auxiliary = await client.get(
                "/content/lookup", params={"type": "object", "id": 32}
            )
            assert auxiliary.status_code == 200
            aux_payload = auxiliary.json()
            assert aux_payload["message_id"] == "MAGF02"
            assert "fountain" in aux_payload["text"].lower()

            missing = await client.get(
                "/content/lookup", params={"type": "spell", "id": 9999}
            )
            assert missing.status_code == 404
            assert missing.json()["detail"]
