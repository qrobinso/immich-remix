import httpx
import pytest
import respx

from app.providers.base import AuthError, ContentRefused, MediaType, ProviderConfig, RemixRequest
from app.providers.stability import Stability

BASE = "https://api.stability.ai"
IMG = b"\x89PNG-out"


def ok(headers=None):
    return httpx.Response(200, content=IMG, headers={"content-type": "image/png", "finish-reason": "SUCCESS", **(headers or {})})


@pytest.fixture
def router():
    with respx.MockRouter(assert_all_called=False) as r:
        yield r


@pytest.fixture
async def st(router):
    async with httpx.AsyncClient(transport=httpx.MockTransport(router.handler)) as http:
        yield Stability(ProviderConfig(api_key="SECRET-KEY", model=None, url=None, options={}), http)


def req(**kw):
    base = dict(media_type=MediaType.IMAGE, data=b"jpg", mime="image/jpeg", prompt="Make it a cartoon.",
                negative_prompt=None, strength=None, variations=1, seed=None, style_reference=None, options={})
    return RemixRequest(**{**base, **kw})


async def test_style_image_from_preset_sent(st, router):
    route = router.post(f"{BASE}/v2beta/stable-image/control/style-transfer").mock(return_value=ok())
    res = await st.remix(req(style_reference=b"STYLEPIX", negative_prompt="blur"))
    sent = route.calls[0].request
    assert sent.headers["authorization"] == "Bearer SECRET-KEY" and sent.headers["accept"] == "image/*"
    body = sent.content
    assert b'name="init_image"' in body and b"jpg" in body
    assert b'name="style_image"' in body and b"STYLEPIX" in body
    assert b'name="negative_prompt"\r\n\r\nblur' in body
    assert res.outputs == [IMG] and res.mime == "image/png" and res.provider_model == "style-transfer"
    assert res.cost_estimate_usd == pytest.approx(0.08)


async def test_no_reference_uses_structure_control(st, router):
    route = router.post(f"{BASE}/v2beta/stable-image/control/structure").mock(return_value=ok())
    res = await st.remix(req(negative_prompt="blur", seed=3, strength=0.4))
    body = route.calls[0].request.content
    assert b'name="image"; filename="image"' in body and b"jpg" in body
    assert b'name="prompt"\r\n\r\nMake it a cartoon.' in body and b'name="negative_prompt"\r\n\r\nblur' in body
    assert b'name="control_strength"\r\n\r\n0.6' in body and b'name="seed"\r\n\r\n3' in body
    assert b'name="output_format"\r\n\r\npng' in body
    assert b"style_image" not in body and b"fidelity" not in body
    assert res.provider_model == "control/structure" and res.cost_estimate_usd == pytest.approx(0.05)


async def test_forced_style_transfer_without_reference_falls_back_to_structure(router):
    async with httpx.AsyncClient(transport=httpx.MockTransport(router.handler)) as http:
        st = Stability(ProviderConfig(api_key="k", model="style-transfer", url=None, options={}), http)
        route = router.post(f"{BASE}/v2beta/stable-image/control/structure").mock(return_value=ok())
        assert (await st.remix(req())).provider_model == "control/structure" and route.called


async def test_strength_passed(st, router):
    t = router.post(f"{BASE}/v2beta/stable-image/control/style-transfer").mock(return_value=ok())
    g = router.post(f"{BASE}/v2beta/stable-image/control/structure").mock(return_value=ok())
    await st.remix(req(style_reference=b"s", strength=0.6, seed=7))
    assert b'name="change_strength"\r\n\r\n0.6' in t.calls[0].request.content
    assert b'name="seed"\r\n\r\n7' in t.calls[0].request.content
    await st.remix(req(strength=0.25))
    assert b'name="control_strength"\r\n\r\n0.75' in g.calls[0].request.content


async def test_one_call_per_variation(st, router):
    route = router.post(f"{BASE}/v2beta/stable-image/control/structure").mock(return_value=ok())
    res = await st.remix(req(variations=3))
    assert route.call_count == 3 and len(res.outputs) == 3 and res.cost_estimate_usd == pytest.approx(0.15)


async def test_content_filtered_is_refusal(st, router):
    route = router.post(f"{BASE}/v2beta/stable-image/control/structure")
    route.mock(return_value=httpx.Response(200, content=b"blur", headers={"finish-reason": "CONTENT_FILTERED"}))
    with pytest.raises(ContentRefused):
        await st.remix(req())
    route.mock(return_value=httpx.Response(403, json={"name": "content_moderation", "errors": ["flagged"]}))
    with pytest.raises(ContentRefused):
        await st.remix(req())


async def test_auth_error_hides_key(st, router):
    router.post(f"{BASE}/v2beta/stable-image/control/structure").mock(return_value=httpx.Response(401, json={"name": "unauthorized", "errors": ["SECRET-KEY"]}))
    with pytest.raises(AuthError) as e:
        await st.remix(req())
    assert "SECRET-KEY" not in str(e.value)


async def test_generate_core(st, router):
    route = router.post(f"{BASE}/v2beta/stable-image/generate/core").mock(return_value=ok())
    assert await st.generate("a cat") == IMG
    assert b'name="prompt"\r\n\r\na cat' in route.calls[0].request.content


async def test_list_models_and_health(st, router):
    assert {m.id for m in await st.list_models()} == {"style-transfer", "control/structure"}
    router.get(f"{BASE}/v1/user/balance").mock(return_value=httpx.Response(200, json={"credits": 1.5}))
    assert (await st.health()).ok
