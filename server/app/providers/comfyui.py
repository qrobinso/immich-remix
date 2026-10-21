import asyncio
import copy
import json
import mimetypes
import re
import time
import uuid
from pathlib import Path

import httpx
import yaml

from .base import (HealthResult, MediaType, ModelInfo, ProviderConfig, ProviderError, RemixRequest, RemixResult, Timeout,
                   gather_or_cancel)

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "workflows"  # /app/workflows in the image
_WHOLE = re.compile(r"^\{\{(\w+)\}\}$")
_ANY = re.compile(r"\{\{(\w+)\}\}")
_NODE_INPUT = re.compile(r"^\w+\.\w+$")


def _sub(v, values: dict):
    if isinstance(v, dict):
        return {k: _sub(x, values) for k, x in v.items()}
    if isinstance(v, list):
        return [_sub(x, values) for x in v]
    if not isinstance(v, str):
        return v

    def get(name):
        if values.get(name) is None:
            raise ProviderError(f"This workflow needs a value for {{{{{name}}}}} that was not supplied ({name})")
        return values[name]

    if m := _WHOLE.match(v):
        return get(m.group(1))  # typed: numbers stay numbers
    return _ANY.sub(lambda m: str(get(m.group(1))), v)


def fill(graph: dict, values: dict) -> dict:
    """Return a copy of the API-format graph with {{placeholders}} substituted."""
    return _sub(copy.deepcopy(graph), values)


def apply_options(graph: dict, options: dict) -> None:
    """Style options keyed 'node_id.input' override that node input; other keys are not ours."""
    for k, v in options.items():
        if _NODE_INPUT.match(k):
            node, inp = k.split(".")
            if node in graph:
                graph[node].setdefault("inputs", {})[inp] = v


def load_templates(*dirs: Path) -> dict[str, dict]:
    """name -> {media_type, output_node, options, graph}; later dirs override earlier ones of the same name."""
    out: dict[str, dict] = {}
    for d in dirs:
        for j in sorted(d.glob("*.json")) if d.is_dir() else []:
            side = j.with_suffix(".yaml")
            if not side.is_file():
                continue
            try:
                meta = yaml.safe_load(side.read_text()) or {}
                out[j.stem] = {"media_type": MediaType(meta["media_type"]), "output_node": str(meta["output_node"]),
                               "options": meta.get("options") or {}, "graph": json.loads(j.read_text())}
            except (KeyError, ValueError, yaml.YAMLError):
                continue  # a broken user template must not hide the others
    return out


class ComfyUI:
    id = "comfyui"
    name = "ComfyUI"
    leaves_network = False
    max_variations = {MediaType.IMAGE: 4, MediaType.VIDEO: 1}
    max_input_px = 2048
    max_video_seconds = None
    price_per_output = None
    can_generate = False
    DEFAULTS = {"typical_seconds": 60.0, "timeout": 1800.0, "poll_interval": 2.0, "max_video_seconds": None}

    def __init__(self, cfg: ProviderConfig, http: httpx.AsyncClient, sleep=asyncio.sleep, clock=time.monotonic):
        self.cfg, self.http, self.sleep, self.clock = cfg, http, sleep, clock
        o = {**self.DEFAULTS, **cfg.options}
        self.typical_seconds, self.timeout, self.poll_interval = o["typical_seconds"], o["timeout"], o["poll_interval"]
        self.max_video_seconds = o["max_video_seconds"]
        user = Path(cfg.options["data_dir"]) / "workflows" if cfg.options.get("data_dir") else Path("/nonexistent")
        self.templates = load_templates(BUILTIN_DIR, user)

    @property
    def media_types(self) -> set[MediaType]:
        return {t["media_type"] for t in self.templates.values()}

    @property
    def base(self) -> str:
        if not self.cfg.url:
            raise ProviderError("ComfyUI URL is not set")
        return self.cfg.url.rstrip("/")

    async def _call(self, method: str, path: str, timeout: float = 30, **kw) -> httpx.Response:
        try:
            r = await self.http.request(method, self.base + path, timeout=timeout, **kw)
        except httpx.TimeoutException:
            raise Timeout("ComfyUI timed out")
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach ComfyUI ({type(e).__name__})")
        if not r.is_success:
            raise ProviderError(f"ComfyUI error {r.status_code}: {r.text[:200]}")
        return r

    def _pick(self, req: RemixRequest) -> tuple[str, dict]:
        name = req.options.get("workflow") or self.cfg.model
        if not name:
            name = next((n for n, t in self.templates.items() if t["media_type"] == req.media_type), None)
        if name not in self.templates:
            raise ProviderError(f"No ComfyUI workflow template '{name}'" if name else "No ComfyUI workflow for this media type")
        t = self.templates[name]
        if t["media_type"] != req.media_type:
            raise ProviderError(f"Workflow '{name}' is a {t['media_type'].value} workflow, not {req.media_type.value}")
        return name, t

    async def _upload(self, req: RemixRequest) -> str:
        ext = mimetypes.guess_extension(req.mime) or (".mp4" if req.media_type == MediaType.VIDEO else ".png")
        fname = f"remix-{uuid.uuid4().hex}{ext}"
        r = await self._call("POST", "/upload/image", timeout=300, files={"image": (fname, req.data, req.mime)}, data={"overwrite": "true"})
        j = r.json()
        return f"{j['subfolder']}/{j['name']}" if j.get("subfolder") else j["name"]

    async def _run(self, graph: dict, output_node: str, deadline: float) -> list[tuple[bytes, str]]:
        pid = (await self._call("POST", "/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex})).json()["prompt_id"]
        while True:
            entry = (await self._call("GET", f"/history/{pid}")).json().get(pid)
            status = (entry or {}).get("status") or {}
            if status.get("status_str") == "error":
                why = next((m[1].get("exception_message") for m in status.get("messages", [])
                            if m[0] == "execution_error" and isinstance(m[1], dict)), None)
                raise ProviderError(f"ComfyUI workflow failed: {(why or 'unknown error')[:300]}")
            if entry and (entry.get("outputs") or status.get("status_str") == "success"):
                break
            if self.clock() >= deadline:
                raise Timeout("ComfyUI took too long")
            await self.sleep(self.poll_interval)
        files = [f for v in entry["outputs"].get(output_node, {}).values() if isinstance(v, list) for f in v
                 if isinstance(f, dict) and "filename" in f]  # skips flags like "animated": [true]
        if not files:
            raise ProviderError(f"ComfyUI workflow produced no output at node {output_node}")
        outs = []
        for f in files:
            r = await self._call("GET", "/view", timeout=120, params={"filename": f["filename"], "subfolder": f.get("subfolder", ""), "type": f.get("type", "output")})
            outs.append((r.content, mimetypes.guess_type(f["filename"])[0] or "application/octet-stream"))
        return outs

    async def remix(self, req: RemixRequest) -> RemixResult:
        name, t = self._pick(req)
        opts = {**t["options"], **req.options}
        seed0 = req.seed if req.seed is not None else int.from_bytes(uuid.uuid4().bytes[:4], "big")
        values = {"prompt": req.prompt, "negative_prompt": req.negative_prompt or "", "strength": 1.0 if req.strength is None else req.strength,
                  "fps": opts.get("fps"), "frames": opts.get("frames"), "seed": seed0}
        fill(t["graph"], {**values, "input_image": "", "input_video": ""})  # fail before any upload if a value is missing
        deadline = self.clock() + self.timeout
        uploaded = await self._upload(req)
        values["input_image" if req.media_type == MediaType.IMAGE else "input_video"] = uploaded
        n = min(req.variations, self.max_variations[req.media_type])

        async def one(i: int):
            g = fill(t["graph"], {**values, "seed": seed0 + i})
            apply_options(g, opts)
            return await self._run(g, t["output_node"], deadline)

        outs = [o for group in await gather_or_cancel([one(i) for i in range(n)]) for o in group]
        return RemixResult(outputs=[b for b, _ in outs], mime=outs[0][1], provider_model=name, cost_estimate_usd=None)

    async def generate(self, prompt: str) -> bytes:
        raise ProviderError("ComfyUI does not generate from text here")

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=n, label=n, media_types={t["media_type"]}) for n, t in sorted(self.templates.items())]

    async def health(self) -> HealthResult:
        if not self.templates:
            return HealthResult(ok=False, message="No workflow templates")
        await self._call("GET", "/system_stats")
        return HealthResult(ok=True)
