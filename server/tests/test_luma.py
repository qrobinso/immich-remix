import asyncio

import httpx
import pytest
import respx

from app.providers.base import AuthError, ContentRefused, MediaType, ProviderConfig, ProviderError, RemixRequest, Timeout
from app.providers.luma import Luma

MP4 = b"\x00\x00\x00\x18ftypmp42-fake"
OUT = b"OUTPUT-MP4"
BASE = "https://agents.lumalabs.ai/v1"
OUTURL = "https://cdn.example/out.mp4"


class Clock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    async def sleep(self, s):
        self.slept.append(s)
        self.t += s
        await asyncio.sleep(0)  # really yield, so an orphaned sibling would keep polling


@pytest.fixture
def router():
    with respx.MockRouter(assert_all_called=False) as r:
        yield r


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
async def prov(router, clock):
    async with httpx.AsyncClient(transport=httpx.MockTransport(router.handler)) as http:
        yield Luma(ProviderConfig(api_key="SECRET-KEY", model=None, url=None, options={}), http, sleep=clock.sleep, clock=clock.now)


def req(**kw):
    base = dict(media_type=MediaType.VIDEO, data=MP4, mime="video/mp4", prompt="Make it a painting.", negative_prompt=None,
                strength=None, variations=1, seed=None, style_reference=None, options={})
    return RemixRequest(**{**base, **kw})


def mock_flow(router, states, ids=("g1",)):
    create = router.post(f"{BASE}/generations").mock(side_effect=[httpx.Response(201, json={"id": i, "state": "queued", "output": []}) for i in ids])
    for i in ids:
        router.get(f"{BASE}/generations/{i}").mock(side_effect=states)
    router.get(OUTURL).mock(return_value=httpx.Response(200, content=OUT))
    return create


def done(): return httpx.Response(200, json={"id": "g1", "state": "completed", "output": [{"type": "video", "url": OUTURL}]})
def running(): return httpx.Response(200, json={"id": "g1", "state": "dreaming", "output": []})


async def test_inline_source_then_create_task(prov, router):
    import base64, json
    create = mock_flow(router, [done()])
    res = await prov.remix(req(prompt="Painting"))
    c = create.calls[0].request
    assert c.headers["authorization"] == "Bearer SECRET-KEY"
    assert json.loads(c.content) == {"model": "ray-3.2", "type": "video_edit", "prompt": "Painting", "video": {"resolution": "720p"},
                                     "source": {"data": base64.b64encode(MP4).decode(), "media_type": "video/mp4"}}
    assert res.provider_model == "ray-3.2" and res.mime == "video/mp4"


async def test_polls_until_succeeded(prov, router, clock):
    mock_flow(router, [running(), running(), done()])
    await prov.remix(req())
    assert clock.slept == [5.0, 5.0]


async def test_failed_task_maps_error(prov, router):
    mock_flow(router, [httpx.Response(200, json={"id": "g1", "state": "failed", "failure_code": "generation_failed", "failure_reason": "boom"})])
    with pytest.raises(ProviderError) as e:
        await prov.remix(req())
    assert not isinstance(e.value, ContentRefused) and "generation_failed" in str(e.value)


async def test_moderation_is_refusal(prov, router):
    mock_flow(router, [httpx.Response(200, json={"id": "g1", "state": "failed", "failure_code": "content_moderated", "failure_reason": "Flagged"})])
    with pytest.raises(ContentRefused) as e:
        await prov.remix(req())
    assert e.value.reason == "Flagged"


async def test_downloads_output(prov, router):
    mock_flow(router, [done()])
    res = await prov.remix(req())
    assert res.outputs == [OUT] and res.cost_estimate_usd == pytest.approx(0.216 * 5)
    dl = [c for c in router.calls if str(c.request.url) == OUTURL][0].request
    assert "authorization" not in dl.headers


async def test_two_variations_two_tasks(prov, router):
    create = mock_flow(router, [done()], ids=("g1", "g2"))
    res = await prov.remix(req(variations=5))
    assert create.call_count == 2 and len(res.outputs) == 2


async def test_poll_timeout_raises_timeout(prov, router, clock):
    mock_flow(router, [running()] * 400)
    with pytest.raises(Timeout):
        await prov.remix(req())
    assert 900 <= clock.t < 910


async def test_clip_too_large_before_any_call(prov, router):
    with pytest.raises(ProviderError, match="clip too large for Luma; shorten it"):
        await prov.remix(req(data=b"x" * (50 * 1024 * 1024 + 1)))
    assert router.calls.call_count == 0


async def test_auth_error_hides_key(prov, router):
    router.post(f"{BASE}/generations").mock(return_value=httpx.Response(401, json={"detail": "bad SECRET-KEY"}))
    with pytest.raises(AuthError) as e:
        await prov.remix(req())
    assert "SECRET-KEY" not in str(e.value)


async def test_health_and_models(prov):
    assert (await prov.health()).ok
    assert [m.id for m in await prov.list_models()] == ["ray-3.2"]



async def test_sibling_cancelled_when_one_variation_fails(prov, router):
    router.post(f"{BASE}/generations").mock(side_effect=[httpx.Response(201, json={"id": i}) for i in ("g1", "g2")])
    router.get(f"{BASE}/generations/g1").mock(return_value=httpx.Response(200, json={"id": "g1", "state": "failed", "failure_code": "content_moderated", "failure_reason": "x"}))
    sib = router.get(f"{BASE}/generations/g2").mock(return_value=running())
    with pytest.raises(ContentRefused):
        await prov.remix(req(variations=2))
    seen = sib.call_count
    for _ in range(20):
        await asyncio.sleep(0)
    assert sib.call_count == seen
