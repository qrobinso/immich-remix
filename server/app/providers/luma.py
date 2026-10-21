import asyncio
import base64
import time

import httpx

from .base import (AuthError, ContentRefused, HealthResult, MediaType, ModelInfo, ProviderConfig, ProviderError,
                   RateLimited, RemixRequest, RemixResult, Timeout, gather_or_cancel)

BASE = "https://agents.lumalabs.ai/v1"
MAX_INPUT_BYTES = 50 * 1024 * 1024


class Luma:
    id = "luma"
    name = "Luma"
    media_types = {MediaType.VIDEO}
    leaves_network = True
    max_variations = {MediaType.VIDEO: 2}
    max_input_px = 1280
    can_generate = False
    # Docs read 2026-10-21: docs.agents.lumalabs.ai (base https://agents.lumalabs.ai/v1, Bearer auth, POST /v1/generations,
    # GET /v1/generations/{id}), /guides/videos/editing (type "video_edit", model "ray-3.2", prompt 1-6000, source.data = inline
    # base64 + media_type, source <= 18 s, output[].url presigned 1 h), /guides/error-handling (state completed|failed,
    # failure_code content_moderated, 413 above 50 MB input), /guides/pricing (video edit 720p: $1.08 per 5 s -> $0.216/s).
    # The older api.lumalabs.ai Modify Video API (docs.lumalabs.ai/reference/modifyvideo) is public-URL only, so it is not used.
    # Editing page says 200 MB, error table says 50 MB; we enforce the stricter 50 MB on the raw clip.
    DEFAULT_MODEL = "ray-3.2"
    DEFAULTS = {"price_per_output": {"video": 0.216}, "max_video_seconds": 10.0, "typical_seconds": 5.0, "timeout": 900.0,
                "poll_interval": 5.0}

    def __init__(self, cfg: ProviderConfig, http: httpx.AsyncClient, sleep=asyncio.sleep, clock=time.monotonic):
        self.cfg, self.http, self.sleep, self.clock = cfg, http, sleep, clock
        self.model = cfg.model or self.DEFAULT_MODEL
        o = {**self.DEFAULTS, **cfg.options}
        self.price_per_output, self.max_video_seconds = o["price_per_output"], o["max_video_seconds"]
        self.typical_seconds, self.timeout, self.poll_interval = o["typical_seconds"], o["timeout"], o["poll_interval"]

    async def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = await self.http.request(method, BASE + path, timeout=60, headers={"Authorization": f"Bearer {self.cfg.api_key or ''}"}, **kw)
        except httpx.TimeoutException:
            raise Timeout("Luma timed out")
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Luma ({type(e).__name__})")
        if r.is_success:
            return r.json()
        if r.status_code in (401, 403):
            raise AuthError("Luma rejected the API key")
        if r.status_code == 429:
            raise RateLimited("Luma rate limit reached")
        if r.status_code == 413:
            raise ProviderError("clip too large for Luma; shorten it")
        try:
            msg = str(r.json().get("detail") or "")
        except (ValueError, AttributeError):
            msg = ""
        raise ProviderError(f"Luma error {r.status_code}: {msg[:200]}")

    async def _task(self, source: dict, req: RemixRequest, deadline: float) -> bytes:
        body = {"model": self.model, "type": "video_edit", "prompt": req.prompt[:6000], "source": source,
                "video": {"resolution": "720p"}}
        gid = (await self._call("POST", "/generations", json=body))["id"]
        while True:
            g = await self._call("GET", f"/generations/{gid}")
            if g["state"] == "completed":
                break
            if g["state"] == "failed":
                code, why = g.get("failure_code") or "", g.get("failure_reason") or ""
                if any(w in code.lower() for w in ("safety", "moderat", "content")):
                    raise ContentRefused(why[:300] or code)
                raise ProviderError(f"Luma generation failed: {code} {why[:200]}".strip())
            if self.clock() >= deadline:
                raise Timeout("Luma video took too long")
            await self.sleep(self.poll_interval)
        try:  # provider-hosted presigned URL: no key
            r = await self.http.get(g["output"][0]["url"], timeout=120)
        except httpx.HTTPError as e:
            raise ProviderError(f"Luma download failed ({type(e).__name__})")
        if not r.is_success:
            raise ProviderError(f"Luma download failed ({r.status_code})")
        return r.content

    async def remix(self, req: RemixRequest) -> RemixResult:
        if len(req.data) > MAX_INPUT_BYTES:
            raise ProviderError("clip too large for Luma; shorten it (50 MB limit)")
        deadline = self.clock() + self.timeout
        source = {"data": base64.b64encode(req.data).decode(), "media_type": "video/mp4"}
        n = min(req.variations, self.max_variations[MediaType.VIDEO])
        outs = await gather_or_cancel([self._task(source, req, deadline) for _ in range(n)])
        price = (self.price_per_output or {}).get("video")
        cost = price * (self.typical_seconds or 0) * n if price is not None and self.typical_seconds else None
        return RemixResult(outputs=list(outs), mime="video/mp4", provider_model=self.model, cost_estimate_usd=cost)

    async def generate(self, prompt: str) -> bytes:
        raise ProviderError("Luma does not generate from text here")

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=self.model, label=self.model, media_types={MediaType.VIDEO})]

    async def health(self) -> HealthResult:
        # shortcut: no cheap authenticated GET is documented; a bad key surfaces on the first job. Upgrade if Luma adds one.
        return HealthResult(ok=bool(self.cfg.api_key), message=None if self.cfg.api_key else "No API key set")
