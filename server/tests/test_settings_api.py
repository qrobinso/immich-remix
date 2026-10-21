import httpx
import pytest

from app.providers.base import ProviderError
from app.providers.registry import PROVIDER_CLASSES


def test_keys_never_returned(client):
    assert client.put("/api/settings", json={"providers.gemini.api_key": "sk-secret-123"}).status_code == 200
    r = client.get("/api/settings")
    assert "sk-secret-123" not in r.text
    g = next(p for p in r.json()["providers"] if p["id"] == "gemini")
    assert g["key_set"] is True and g["key_source"] == "db" and g["model"] == "gemini-3.1-flash-image"
    assert len(r.json()["providers"]) == len(PROVIDER_CLASSES)
    assert r.json()["sources"]["providers.gemini.api_key"] == "db"
    assert client.put("/api/settings", json={"providers.gemini.api_key": ""}).status_code == 200
    assert client.get("/api/settings").json()["values"]["providers.gemini.api_key"]["set"] is False


def test_env_key_put_409(make_client):
    with make_client(GEMINI_API_KEY="envkey") as c:
        r = c.put("/api/settings", json={"photo.max_px": 1024, "providers.gemini.api_key": "x"})
        assert r.status_code == 409 and "providers.gemini.api_key" in r.text
        assert c.get("/api/settings").json()["values"]["photo.max_px"] == 2048  # nothing written
        assert "envkey" not in c.get("/api/settings").text


@pytest.mark.parametrize("body", [
    {"photo.max_px": 10}, {"photo.jpeg_quality": 101}, {"photo.source": "x"}, {"video.max_height": 500},
    {"video.keep_audio": "yes"}, {"cleanup.days": 0}, {"save.stack_primary": "x"}, {"save.album": ""},
    {"save.tag": "t" * 51}, {"default_provider.image": "nope"}, {"styles.category_order": ["bogus"]},
    {"providers.gemini.enabled": 1}, {"providers.gemini.url": "x"}, {"providers.comfyui.url": "ftp://h"},
    {"providers.gemini.timeout": -1}, {"nonsense": 1}, {"photo.max_px": True},
])
def test_invalid_value_422(client, body):
    key = next(iter(body))
    r = client.put("/api/settings", json=body)
    assert r.status_code == 422 and key in r.text


def test_invalid_is_all_or_nothing(client):
    assert client.put("/api/settings", json={"photo.max_px": 1024, "photo.jpeg_quality": 101}).status_code == 422
    assert client.get("/api/settings").json()["values"]["photo.max_px"] == 2048


def test_valid_put(client):
    body = {"photo.max_px": 1024, "save.album": None, "providers.comfyui.url": "http://c:8188", "providers.gemini.timeout": 5}
    assert client.put("/api/settings", json=body).status_code == 200
    v = client.get("/api/settings").json()["values"]
    assert v["photo.max_px"] == 1024 and v["save.album"] is None and v["providers.comfyui.url"] == "http://c:8188"


def test_models_endpoint_fallback(client, monkeypatch):
    async def boom(self):
        raise ProviderError("secret detail")

    monkeypatch.setattr(PROVIDER_CLASSES["gemini"], "list_models", boom)
    r = client.get("/api/providers/gemini/models")
    assert r.status_code == 200 and r.json()["fallback"] is True and "secret detail" not in r.text
    assert client.get("/api/providers/nope/models").status_code == 404


def test_models_endpoint_ok(client, monkeypatch):
    from app.providers.base import ModelInfo

    async def ok(self):
        return [ModelInfo(id="m", label="M", media_types={"image"})]

    monkeypatch.setattr(PROVIDER_CLASSES["gemini"], "list_models", ok)
    assert client.get("/api/providers/gemini/models").json()[0]["id"] == "m"


def test_provider_test_endpoint(client, monkeypatch):
    from app.providers.base import HealthResult

    async def h(self):
        return HealthResult(ok=True)

    monkeypatch.setattr(PROVIDER_CLASSES["gemini"], "health", h)
    assert client.post("/api/providers/gemini/test").json() == {"ok": True, "message": None}
    assert client.post("/api/providers/nope/test").status_code == 404


def test_provider_toggle_refreshes_registry(client):
    reg, calls = client.app.state.providers, []
    orig = reg.refresh_health

    async def spy():
        calls.append(1)
        await orig()

    reg.refresh_health = spy
    client.put("/api/settings", json={"photo.max_px": 1024})
    assert calls == []
    client.put("/api/settings", json={"providers.gemini.enabled": True})
    assert calls == [1]


def test_albums(client, immich_mock):
    immich_mock.get("/api/albums").mock(return_value=httpx.Response(200, json=[{"id": "a1", "albumName": "Remixes", "x": 1}]))
    assert client.get("/api/albums").json() == [{"id": "a1", "name": "Remixes"}]
    immich_mock.get("/api/albums").mock(return_value=httpx.Response(500))
    assert client.get("/api/albums").status_code == 502
