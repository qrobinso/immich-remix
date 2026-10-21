import base64
import json

import httpx
import pytest
import respx

from app.providers.base import AuthError, ContentRefused, MediaType, RateLimited, RemixRequest, Timeout
from app.providers.gemini import Gemini
from app.providers.base import ProviderConfig
from app.providers.registry import Registry

BASE = "https://generativelanguage.googleapis.com/v1beta"
GEN = f"{BASE}/models/gemini-3.1-flash-image:generateContent"
PNG = b"\x89PNG-fake"


def image_reply(data=PNG, key="inlineData"):
    part = {key: {("mimeType" if key == "inlineData" else "mime_type"): "image/png", "data": base64.b64encode(data).decode()}}
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "ok"}, part]}, "finishReason": "STOP"}]})


@pytest.fixture
def router():
    with respx.MockRouter(assert_all_called=False) as r:
        yield r


@pytest.fixture
async def gem(router):
    async with httpx.AsyncClient(transport=httpx.MockTransport(router.handler)) as http:
        yield Gemini(ProviderConfig(api_key="SECRET-KEY", model=None, url=None, options={}), http)


def req(**kw):
    base = dict(media_type=MediaType.IMAGE, data=b"jpg", mime="image/jpeg", prompt="Make it a cartoon.",
                negative_prompt=None, strength=None, variations=1, seed=None, style_reference=None, options={})
    return RemixRequest(**{**base, **kw})


async def test_remix_parses_image(gem, router):
    route = router.post(GEN).mock(return_value=image_reply())
    res = await gem.remix(req(negative_prompt="blur"))
    assert res.outputs == [PNG] and res.mime == "image/png"
    assert res.provider_model == "gemini-3.1-flash-image" and res.cost_estimate_usd == pytest.approx(0.067)
    sent = route.calls[0].request
    assert sent.headers["x-goog-api-key"] == "SECRET-KEY"
    body = json.loads(sent.content)
    parts = body["contents"][0]["parts"]
    assert parts[0]["inline_data"] == {"mime_type": "image/jpeg", "data": base64.b64encode(b"jpg").decode()}
    assert parts[1]["text"] == "Make it a cartoon. Avoid: blur"
    assert body["generationConfig"]["responseModalities"] == ["IMAGE"]


async def test_snake_case_inline_data(gem, router):
    router.post(GEN).mock(return_value=image_reply(key="inline_data"))
    assert (await gem.remix(req())).outputs == [PNG]


async def test_text_only_answer_is_refusal(gem, router):
    reply = {"candidates": [{"content": {"parts": [{"text": "I can't edit that."}]}, "finishReason": "STOP"}]}
    router.post(GEN).mock(return_value=httpx.Response(200, json=reply))
    with pytest.raises(ContentRefused) as e:
        await gem.remix(req())
    assert e.value.reason == "I can't edit that."


async def test_safety_block_is_refusal(gem, router):
    router.post(GEN).mock(return_value=httpx.Response(200, json={"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}))
    with pytest.raises(ContentRefused) as e:
        await gem.remix(req())
    assert "PROHIBITED_CONTENT" in e.value.reason
    router.post(GEN).mock(return_value=httpx.Response(200, json={"candidates": [{"finishReason": "IMAGE_SAFETY"}]}))
    with pytest.raises(ContentRefused) as e:
        await gem.remix(req())
    assert "IMAGE_SAFETY" in e.value.reason


@pytest.mark.parametrize("status", [401, 403])
async def test_401_auth_error(gem, router, status):
    router.post(GEN).mock(return_value=httpx.Response(status, json={"error": {"message": "bad key SECRET-KEY"}}))
    with pytest.raises(AuthError) as e:
        await gem.remix(req())
    assert "SECRET-KEY" not in str(e.value)


async def test_429_rate_limited(gem, router):
    router.post(GEN).mock(return_value=httpx.Response(429))
    with pytest.raises(RateLimited):
        await gem.remix(req())


async def test_timeout(gem, router):
    router.post(GEN).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(Timeout):
        await gem.remix(req())


async def test_variations_call_n_times(gem, router):
    route = router.post(GEN).mock(return_value=image_reply())
    res = await gem.remix(req(variations=3))
    assert route.call_count == 3 and len(res.outputs) == 3 and res.cost_estimate_usd == pytest.approx(0.201)


async def test_generate_text_only(gem, router):
    route = router.post(GEN).mock(return_value=image_reply())
    assert await gem.generate("a cat") == PNG
    assert json.loads(route.calls[0].request.content)["contents"][0]["parts"] == [{"text": "a cat"}]


MODELS = {"models": [
    {"name": "models/gemini-3.1-flash-image", "displayName": "Nano Banana 2"},
    {"name": "models/gemini-3.1-pro", "displayName": "Pro"},
]}


async def test_list_models_filters_image(gem, router):
    router.get(f"{BASE}/models", params={"pageSize": "200"}).mock(return_value=httpx.Response(200, json=MODELS))
    [m] = await gem.list_models()
    assert (m.id, m.label, m.media_types) == ("gemini-3.1-flash-image", "Nano Banana 2 · gemini-3.1-flash-image", {MediaType.IMAGE})


async def test_registry_hides_unhealthy(client, router):
    s = client.app.state.settings
    s.set("providers.gemini.enabled", True)
    s.set("providers.gemini.api_key", "SECRET-KEY")
    async with httpx.AsyncClient(transport=httpx.MockTransport(router.handler)) as http:
        reg = Registry(s, http)
        router.get(f"{BASE}/models").mock(return_value=httpx.Response(401, json={"error": {"message": "SECRET-KEY"}}))
        await reg.refresh_health()
        assert [p.id for p in reg.enabled()] == ["gemini"] and reg.for_media(MediaType.IMAGE) == []
        h = reg.health["gemini"]
        assert not h.ok and "SECRET-KEY" not in h.message
        router.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json=MODELS))
        await reg.refresh_health()
        assert [p.id for p in reg.for_media(MediaType.IMAGE)] == ["gemini"]
        assert reg.for_media(MediaType.VIDEO) == []
        assert reg.get("gemini").id == "gemini"


async def test_registry_ignores_disabled(client):
    reg = Registry(client.app.state.settings, httpx.AsyncClient())
    assert reg.enabled() == []


def test_status_lists_providers(make_client):
    with make_client(GEMINI_API_KEY="SECRET-KEY") as c:
        # the autouse respx mock blocks Google, so the startup health check fails harmlessly
        [p] = c.get("/api/status").json()["providers"]
        assert p["id"] == "gemini" and p["healthy"] is False and "SECRET-KEY" not in str(p)
        assert p["media_types"] == ["image"] and p["price_per_output"] == {"image": 0.067}
