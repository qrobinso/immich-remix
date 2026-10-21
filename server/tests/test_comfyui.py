import asyncio
import json

import httpx
import pytest
import respx

from app.providers.base import MediaType, ProviderConfig, ProviderError, RemixRequest, Timeout
from app.providers.comfyui import apply_options, fill
from app.providers.comfyui import ComfyUI

BASE = "http://comfy.test"
PNG = b"\x89PNG-input"
OUT = b"OUT-PNG"


@pytest.fixture
def router():
    with respx.MockRouter(assert_all_called=False) as r:
        yield r


def make(router, tmp_path, **opts):
    http = httpx.AsyncClient(transport=httpx.MockTransport(router.handler))
    t = {"t": 0.0}

    async def sleep(s):
        t["t"] += s
        await asyncio.sleep(0)

    cfg = ProviderConfig(api_key=None, model=None, url=BASE, options={"data_dir": str(tmp_path), **opts})
    return ComfyUI(cfg, http, sleep=sleep, clock=lambda: t["t"])


def user_template(tmp_path, name, graph, media_type="image", output_node="9"):
    d = tmp_path / "workflows"
    d.mkdir(exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps(graph))
    (d / f"{name}.yaml").write_text(f"name: {name}\nmedia_type: {media_type}\noutput_node: '{output_node}'\noptions: {{}}\n")


def req(**kw):
    base = dict(media_type=MediaType.IMAGE, data=PNG, mime="image/png", prompt="Paint it", negative_prompt="blur", strength=0.5,
                variations=1, seed=42, style_reference=None, options={})
    return RemixRequest(**{**base, **kw})


GRAPH = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{input_image}}"}},
         "2": {"class_type": "KSampler", "inputs": {"seed": "{{seed}}", "denoise": "{{strength}}", "steps": 20}},
         "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "Style: {{prompt}}!"}}}


def test_whole_placeholder_typed():
    out = fill(GRAPH, {"seed": 42, "strength": 0.5, "input_image": "a.png", "prompt": "x"})
    assert out["2"]["inputs"]["seed"] == 42 and isinstance(out["2"]["inputs"]["seed"], int)
    assert out["2"]["inputs"]["denoise"] == 0.5
    assert GRAPH["2"]["inputs"]["seed"] == "{{seed}}"  # template untouched


def test_inline_placeholder_text():
    out = fill(GRAPH, {"seed": 1, "strength": 1, "input_image": "a.png", "prompt": "oil"})
    assert out["3"]["inputs"]["text"] == "Style: oil!"


def test_options_override_node_input():
    g = fill(GRAPH, {"seed": 1, "strength": 1, "input_image": "a", "prompt": "p"})
    apply_options(g, {"2.steps": 30, "workflow": "x", "steps": 5, "9.nope": 1})
    assert g["2"]["inputs"]["steps"] == 30 and "9" not in g


async def test_missing_value_raises():
    with pytest.raises(ProviderError):
        fill({"1": {"inputs": {"fps": "{{fps}}"}}}, {})


async def test_flow_upload_prompt_history_view(router, tmp_path):
    user_template(tmp_path, "mine", GRAPH, output_node="2")
    p = make(router, tmp_path)
    router.post(f"{BASE}/upload/image").mock(return_value=httpx.Response(200, json={"name": "up.png", "subfolder": "sub", "type": "input"}))
    sent = router.post(f"{BASE}/prompt").mock(side_effect=[httpx.Response(200, json={"prompt_id": "p0"}), httpx.Response(200, json={"prompt_id": "p1"})])
    entry = {"outputs": {"2": {"images": [{"filename": "o.png", "subfolder": "", "type": "output"}]}}, "status": {"status_str": "success"}}
    router.get(f"{BASE}/history/p0").mock(side_effect=[httpx.Response(200, json={}), httpx.Response(200, json={"p0": entry})])
    router.get(f"{BASE}/history/p1").mock(return_value=httpx.Response(200, json={"p1": entry}))
    view = router.get(f"{BASE}/view").mock(return_value=httpx.Response(200, content=OUT))
    res = await p.remix(req(variations=2, options={"workflow": "mine", "2.steps": 7}))
    up = router.calls[0].request
    assert b'name="image"' in up.content and PNG in up.content and b'name="overwrite"' in up.content
    bodies = [json.loads(c.request.content) for c in sent.calls]
    assert [b["prompt"]["2"]["inputs"]["seed"] for b in bodies] == [42, 43]
    assert bodies[0]["prompt"]["1"]["inputs"]["image"] == "sub/up.png" and bodies[0]["prompt"]["2"]["inputs"]["steps"] == 7
    assert bodies[0]["client_id"]
    assert view.calls[0].request.url.params["filename"] == "o.png" and view.calls[0].request.url.params["type"] == "output"
    assert res.outputs == [OUT, OUT] and res.mime == "image/png" and res.provider_model == "mine"


async def test_execution_error_surfaces(router, tmp_path):
    user_template(tmp_path, "mine", GRAPH, output_node="2")
    p = make(router, tmp_path)
    router.post(f"{BASE}/upload/image").mock(return_value=httpx.Response(200, json={"name": "u.png", "subfolder": ""}))
    router.post(f"{BASE}/prompt").mock(return_value=httpx.Response(200, json={"prompt_id": "p0"}))
    msgs = [["execution_error", {"exception_message": "Out of memory"}]]
    router.get(f"{BASE}/history/p0").mock(return_value=httpx.Response(200, json={"p0": {"outputs": {}, "status": {"status_str": "error", "messages": msgs}}}))
    with pytest.raises(ProviderError, match="Out of memory"):
        await p.remix(req(options={"workflow": "mine"}))


async def test_timeout(router, tmp_path):
    user_template(tmp_path, "mine", GRAPH, output_node="2")
    p = make(router, tmp_path, timeout=10, poll_interval=2)
    router.post(f"{BASE}/upload/image").mock(return_value=httpx.Response(200, json={"name": "u.png", "subfolder": ""}))
    router.post(f"{BASE}/prompt").mock(return_value=httpx.Response(200, json={"prompt_id": "p0"}))
    router.get(f"{BASE}/history/p0").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(Timeout):
        await p.remix(req(options={"workflow": "mine"}))


async def test_user_template_overrides(router, tmp_path):
    builtin = make(router, tmp_path)
    assert "qwen-image-edit" in builtin.templates and builtin.templates["qwen-image-edit"]["output_node"] != "77"
    user_template(tmp_path, "qwen-image-edit", GRAPH, output_node="77")
    p = make(router, tmp_path)
    assert p.templates["qwen-image-edit"]["output_node"] == "77"
    assert {m.id for m in await p.list_models()} >= {"qwen-image-edit", "flux-kontext", "wan-vace"}


async def test_video_template_only_for_video(router, tmp_path):
    p = make(router, tmp_path)
    assert p.media_types == {MediaType.IMAGE, MediaType.VIDEO}
    models = {m.id: m.media_types for m in await p.list_models()}
    assert models["wan-vace"] == {MediaType.VIDEO} and models["flux-kontext"] == {MediaType.IMAGE}
    with pytest.raises(ProviderError, match="video"):
        await p.remix(req(options={"workflow": "wan-vace"}))
    with pytest.raises(ProviderError, match="frames|fps"):
        await p.remix(req(media_type=MediaType.VIDEO, mime="video/mp4", options={"workflow": "wan-vace"}))


async def test_health(router, tmp_path):
    p = make(router, tmp_path)
    router.get(f"{BASE}/system_stats").mock(return_value=httpx.Response(200, json={}))
    assert (await p.health()).ok
    p.templates = {}
    assert not (await p.health()).ok


async def test_video_shaped_history_downloads_mp4(router, tmp_path):
    user_template(tmp_path, "vid", GRAPH, media_type="video", output_node="2")
    p = make(router, tmp_path)
    router.post(f"{BASE}/upload/image").mock(return_value=httpx.Response(200, json={"name": "u.mp4", "subfolder": ""}))
    router.post(f"{BASE}/prompt").mock(return_value=httpx.Response(200, json={"prompt_id": "p0"}))
    entry = {"outputs": {"2": {"images": [{"filename": "o.mp4", "subfolder": "v", "type": "output"}], "animated": [True]}},
             "status": {"status_str": "success"}}
    router.get(f"{BASE}/history/p0").mock(return_value=httpx.Response(200, json={"p0": entry}))
    router.get(f"{BASE}/view").mock(return_value=httpx.Response(200, content=b"MP4"))
    res = await p.remix(req(media_type=MediaType.VIDEO, mime="video/mp4", options={"workflow": "vid", "fps": 16, "frames": 49}))
    assert res.outputs == [b"MP4"] and res.mime == "video/mp4"
