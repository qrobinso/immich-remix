import base64
import json

import httpx
import pytest
import respx

from app.providers.base import AuthError, ContentRefused, MediaType, ProviderConfig, RemixRequest
from app.providers.openai import OpenAI

BASE = "https://api.openai.com/v1"
PNG = b"\x89PNG-fake"


def reply(n=1):
    return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(PNG + bytes([i])).decode()} for i in range(n)]})


@pytest.fixture
def router():
    with respx.MockRouter(assert_all_called=False) as r:
        yield r


@pytest.fixture
async def oa(router):
    async with httpx.AsyncClient(transport=httpx.MockTransport(router.handler)) as http:
        yield OpenAI(ProviderConfig(api_key="SECRET-KEY", model=None, url=None, options={}), http)


def req(**kw):
    base = dict(media_type=MediaType.IMAGE, data=b"jpg", mime="image/jpeg", prompt="Make it a cartoon.",
                negative_prompt=None, strength=None, variations=1, seed=None, style_reference=None, options={})
    return RemixRequest(**{**base, **kw})


async def test_edit_multipart_fields(oa, router):
    route = router.post(f"{BASE}/images/edits").mock(return_value=reply())
    res = await oa.remix(req(negative_prompt="blur"))
    assert res.outputs == [PNG + b"\x00"] and res.mime == "image/png" and res.provider_model == "gpt-image-2.5-sunburst"
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer SECRET-KEY"
    assert sent.headers["content-type"].startswith("multipart/form-data")
    body = sent.content
    assert b'name="model"\r\n\r\ngpt-image-2.5-sunburst' in body
    assert b'name="prompt"\r\n\r\nMake it a cartoon. Avoid: blur' in body
    assert b'name="n"\r\n\r\n1' in body
    assert b'name="image"; filename="image.jpg"' in body and b"Content-Type: image/jpeg" in body and b"jpg" in body


async def test_n_variations_single_call(oa, router):
    route = router.post(f"{BASE}/images/edits").mock(return_value=reply(3))
    res = await oa.remix(req(variations=3))
    assert route.call_count == 1 and b'name="n"\r\n\r\n3' in route.calls[0].request.content
    assert len(res.outputs) == 3 and res.cost_estimate_usd == pytest.approx(3 * oa.price_per_output["image"])


@pytest.mark.parametrize("code", ["moderation_blocked", "content_policy_violation"])
async def test_moderation_error_is_refusal(oa, router, code):
    router.post(f"{BASE}/images/edits").mock(return_value=httpx.Response(400, json={"error": {"code": code, "message": "Blocked by safety"}}))
    with pytest.raises(ContentRefused) as e:
        await oa.remix(req())
    assert e.value.reason == "Blocked by safety"


async def test_auth_error_hides_key(oa, router):
    router.post(f"{BASE}/images/edits").mock(return_value=httpx.Response(401, json={"error": {"message": "bad SECRET-KEY"}}))
    with pytest.raises(AuthError) as e:
        await oa.remix(req())
    assert "SECRET-KEY" not in str(e.value)


async def test_generate(oa, router):
    route = router.post(f"{BASE}/images/generations").mock(return_value=reply())
    assert await oa.generate("a cat") == PNG + b"\x00"
    assert json.loads(route.calls[0].request.content) == {"model": "gpt-image-2.5-sunburst", "prompt": "a cat", "n": 1}


async def test_list_models(oa, router):
    router.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json={"data": [
        {"id": "gpt-image-2.5-flare"}, {"id": "dall-e-3"}, {"id": "gpt-6-luna"}]}))
    assert [(m.id, m.label, m.media_types) for m in await oa.list_models()] == [
        ("gpt-image-2.5-flare", "gpt-image-2.5-flare", {MediaType.IMAGE}), ("dall-e-3", "dall-e-3", {MediaType.IMAGE})]
    router.get(f"{BASE}/models").mock(return_value=httpx.Response(200, json={"data": []}))
    assert (await oa.health()).ok
