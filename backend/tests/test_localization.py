import json

import httpx
import pytest

from kyrgame import fixtures
from kyrgame.webapp import create_app
from kyrgame.scripts import package_content



def test_message_bundle_fixture_includes_version_and_locale():
    bundle = fixtures.load_message_bundle("en-US")

    assert bundle.locale == "en-US"
    assert bundle.version.startswith("legacy-")
    assert bundle.catalog_id == "kyrandia-legacy"
    assert "FOREST" in bundle.messages


@pytest.mark.anyio
async def test_localized_bundle_api_matches_fixture_snapshot():
    app = create_app()
    expected_bundle = fixtures.load_message_bundle("en-US")

    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/i18n/en-US/messages")

    assert response.status_code == 200
    assert response.json() == expected_bundle.model_dump()



def test_offline_packager_writes_bundle(tmp_path):
    output_file = tmp_path / "bundle.json"

    written_path = package_content.build_offline_bundle(output_file)

    assert written_path == output_file
    assert output_file.exists()

    payload = json.loads(output_file.read_text(encoding="utf-8"))
    assert payload["messages"]["locale"] == "en-US"
    assert payload["messages"]["version"].startswith("legacy-")
