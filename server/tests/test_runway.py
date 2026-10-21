import asyncio

import httpx
import pytest
import respx

from app.providers.base import AuthError, ContentRefused, MediaType, ProviderConfig, ProviderError, RemixRequest, Timeout
from app.providers.runway import Runway

MP4 = b"\x00\x00\x00\x18ftypmp42-fake"
OUT = b"OUTPUT-MP4"
BASE = "https://api.dev.runwayml.com"
UP = "https://storage.example/upload"
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
        yield Runway(ProviderConfig(api_key="SECRET-KEY", model=None, url=None, options={}), http, sleep=clock.sleep, clock=clock.now)


def req(**kw):
    base = dict(media_type=MediaType.VIDEO, data=MP4, mime="video/mp4", prompt="Make it a painting.", negative_prompt=None,
                strength=None, variations=1, seed=None, style_reference=None, options={})
    return RemixRequest(**{**base, **kw})


def mock_flow(router, statuses, ids=("t1",)):
    router.post(f"{BASE}/v1/uploads").mock(return_value=httpx.Response(200, json={
        "uploadUrl": UP, "fields": {"key": "k1", "policy": "p"}, "runwayUri": "runway://abc"}))
    up = router.post(UP).mock(return_value=httpx.Response(204))
    create = router.post(f"{BASE}/v1/video_to_video").mock(side_effect=[httpx.Response(200, json={"id": i, "estimatedCost": {"credits": 56}}) for i in ids])
    for i in ids:
        router.get(f"{BASE}/v1/tasks/{i}").mock(side_effect=statuses)
    router.get(OUTURL).mock(return_value=httpx.Response(200, content=OUT))
    return up, create


def done(): return httpx.Response(200, json={"id": "t1", "status": "SUCCEEDED", "output": [OUTURL]})
def running(): return httpx.Response(200, json={"id": "t1", "status": "RUNNING", "progress": 0.5})


async def test_upload_then_create_task(prov, router):
    up, create = mock_flow(router, [done()])
    res = await prov.remix(req(prompt="Painting", seed=7))
    s = up.calls[0].request
    assert "authorization" not in s.headers  # storage host never sees the key
    assert b'name="key"\r\n\r\nk1' in s.content and b'name="file"' in s.content and MP4 in s.content
    c = create.calls[0].request
    assert c.headers["authorization"] == "Bearer SECRET-KEY" and c.headers["x-runway-version"] == "2024-11-06"
    import json
    assert json.loads(c.content) == {"model": "aleph2", "videoUri": "runway://abc", "promptText": "Painting", "seed": 7}
    assert res.provider_model == "aleph2" and res.mime == "video/mp4"


async def test_polls_until_succeeded(prov, router, clock):
    mock_flow(router, [running(), running(), done()])
    await prov.remix(req())
    assert clock.slept == [5.0, 5.0]


async def test_failed_task_maps_error(prov, router):
    mock_flow(router, [httpx.Response(200, json={"id": "t1", "status": "FAILED", "failure": "boom", "failureCode": "INTERNAL.BAD_OUTPUT.01"})])
    with pytest.raises(ProviderError) as e:
        await prov.remix(req())
    assert not isinstance(e.value, ContentRefused) and "INTERNAL.BAD_OUTPUT.01" in str(e.value)


async def test_moderation_is_refusal(prov, router):
    mock_flow(router, [httpx.Response(200, json={"id": "t1", "status": "FAILED", "failure": "Input rejected", "failureCode": "SAFETY.INPUT.VIDEO"})])
    with pytest.raises(ContentRefused) as e:
        await prov.remix(req())
    assert e.value.reason == "Input rejected"


async def test_downloads_output(prov, router):
    mock_flow(router, [done()])
    res = await prov.remix(req())
    assert res.outputs == [OUT] and res.cost_estimate_usd == pytest.approx(0.28 * 5)
    dl = [c for c in router.calls if str(c.request.url) == OUTURL][0].request
    assert "authorization" not in dl.headers


async def test_two_variations_two_tasks(prov, router):
    _, create = mock_flow(router, [done()], ids=("t1", "t2"))
    res = await prov.remix(req(variations=5))
    assert create.call_count == 2 and len(res.outputs) == 2


async def test_poll_timeout_raises_timeout(prov, router, clock):
    mock_flow(router, [running()] * 400)
    with pytest.raises(Timeout):
        await prov.remix(req())
    assert 900 <= clock.t < 910


async def test_auth_error_hides_key(prov, router):
    router.post(f"{BASE}/v1/uploads").mock(return_value=httpx.Response(401, json={"error": "bad SECRET-KEY"}))
    with pytest.raises(AuthError) as e:
        await prov.remix(req())
    assert "SECRET-KEY" not in str(e.value)


async def test_health_and_models(prov, router):
    router.get(f"{BASE}/v1/organization").mock(return_value=httpx.Response(200, json={"tier": {}}))
    assert (await prov.health()).ok
    assert [m.id for m in await prov.list_models()] == ["aleph2"]



async def test_sibling_cancelled_when_one_variation_fails(prov, router):
    router.post(f"{BASE}/v1/uploads").mock(return_value=httpx.Response(200, json={"uploadUrl": UP, "fields": {}, "runwayUri": "runway://abc"}))
    router.post(UP).mock(return_value=httpx.Response(204))
    router.post(f"{BASE}/v1/video_to_video").mock(side_effect=[httpx.Response(200, json={"id": i}) for i in ("t1", "t2")])
    router.get(f"{BASE}/v1/tasks/t1").mock(return_value=httpx.Response(200, json={"id": "t1", "status": "FAILED", "failure": "x", "failureCode": "SAFETY.INPUT.VIDEO"}))
    sib = router.get(f"{BASE}/v1/tasks/t2").mock(return_value=running())
    with pytest.raises(ContentRefused):
        await prov.remix(req(variations=2))
    seen = sib.call_count
    for _ in range(20):
        await asyncio.sleep(0)
    assert sib.call_count == seen
