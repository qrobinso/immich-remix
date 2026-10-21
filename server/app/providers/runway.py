import asyncio
import time

import httpx

from .base import (AuthError, ContentRefused, HealthResult, MediaType, ModelInfo, ProviderConfig, ProviderError,
                   RateLimited, RemixRequest, RemixResult, Timeout)

BASE = "https://api.dev.runwayml.com"
VERSION = "2024-11-06"


class Runway:
    id = "runway"
    name = "Runway"
    media_types = {MediaType.VIDEO}
    leaves_network = True
    max_variations = {MediaType.VIDEO: 2}
    max_input_px = 1280
    can_generate = False
    # Docs read 2026-10-21: docs.dev.runwayml.com/assets/uploads (POST /v1/uploads type=ephemeral -> uploadUrl+fields+runwayUri,
    # then multipart POST of the file; 512 B-200 MB, URI valid 24 h), /assets/inputs, /openapi.json (video_to_video model "aleph2",
    # videoUri <= 30 s, promptText <= 1000; GET /v1/tasks/{id}: PENDING|THROTTLED|RUNNING|SUCCEEDED|FAILED|CANCELLED, output[],
    # failure, failureCode; GET /v1/organization), /errors/task-failures (SAFETY.* = moderation), /guides/pricing.md
    # (aleph2 = 28 credits/s, 56 minimum; 1 credit = $0.01 -> $0.28/s).
    # Input video goes through the ephemeral upload endpoint, so no public URL is needed.
    DEFAULT_MODEL = "aleph2"
    DEFAULTS = {"price_per_output": {"video": 0.28}, "max_video_seconds": 10.0, "typical_seconds": 5.0, "timeout": 900.0,
                "poll_interval": 5.0}

    def __init__(self, cfg: ProviderConfig, http: httpx.AsyncClient, sleep=asyncio.sleep, clock=time.monotonic):
        self.cfg, self.http, self.sleep, self.clock = cfg, http, sleep, clock
        self.model = cfg.model or self.DEFAULT_MODEL
        o = {**self.DEFAULTS, **cfg.options}
        self.price_per_output, self.max_video_seconds = o["price_per_output"], o["max_video_seconds"]
        self.typical_seconds, self.timeout, self.poll_interval = o["typical_seconds"], o["timeout"], o["poll_interval"]

    async def _call(self, method: str, path: str, **kw) -> dict:
        try:
            r = await self.http.request(method, BASE + path, timeout=30, headers={
                "Authorization": f"Bearer {self.cfg.api_key or ''}", "X-Runway-Version": VERSION}, **kw)
        except httpx.TimeoutException:
            raise Timeout("Runway timed out")
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Runway ({type(e).__name__})")
        if r.is_success:
            return r.json()
        if r.status_code in (401, 403):
            raise AuthError("Runway rejected the API key")
        if r.status_code == 429:
            raise RateLimited("Runway rate limit reached")
        try:
            msg = str(r.json().get("error") or "")
        except (ValueError, AttributeError):
            msg = ""
        raise ProviderError(f"Runway error {r.status_code}: {msg[:200]}")

    async def _upload(self, data: bytes) -> str:
        up = await self._call("POST", "/v1/uploads", json={"filename": "input.mp4", "type": "ephemeral"})
        try:  # the storage host is not Runway's API: never send the key there
            r = await self.http.post(up["uploadUrl"], data=up["fields"], files={"file": ("input.mp4", data, "video/mp4")}, timeout=300)
        except httpx.HTTPError as e:
            raise ProviderError(f"Runway upload failed ({type(e).__name__})")
        if not r.is_success:
            raise ProviderError(f"Runway upload failed ({r.status_code})")
        return up["runwayUri"]

    async def _task(self, uri: str, req: RemixRequest, deadline: float) -> bytes:
        body = {"model": self.model, "videoUri": uri, "promptText": req.prompt[:1000]}
        if req.seed is not None:
            body["seed"] = req.seed
        tid = (await self._call("POST", "/v1/video_to_video", json=body))["id"]
        while True:
            t = await self._call("GET", f"/v1/tasks/{tid}")
            if t["status"] == "SUCCEEDED":
                break
            if t["status"] in ("FAILED", "CANCELLED"):
                code, why = t.get("failureCode") or "", t.get("failure") or t["status"]
                if any(w in code.lower() for w in ("safety", "moderat", "content")):
                    raise ContentRefused(why[:300])
                raise ProviderError(f"Runway task failed: {code} {why[:200]}".strip())
            if self.clock() >= deadline:
                raise Timeout("Runway video took too long")
            await self.sleep(self.poll_interval)
        try:  # provider-hosted presigned URL: no key
            r = await self.http.get(t["output"][0], timeout=120)
        except httpx.HTTPError as e:
            raise ProviderError(f"Runway download failed ({type(e).__name__})")
        if not r.is_success:
            raise ProviderError(f"Runway download failed ({r.status_code})")
        return r.content

    async def remix(self, req: RemixRequest) -> RemixResult:
        deadline = self.clock() + self.timeout
        uri = await self._upload(req.data)
        n = min(req.variations, self.max_variations[MediaType.VIDEO])
        outs = await asyncio.gather(*[self._task(uri, req, deadline) for _ in range(n)])
        price = (self.price_per_output or {}).get("video")
        cost = price * (self.typical_seconds or 0) * n if price is not None and self.typical_seconds else None
        return RemixResult(outputs=list(outs), mime="video/mp4", provider_model=self.model, cost_estimate_usd=cost)

    async def generate(self, prompt: str) -> bytes:
        raise ProviderError("Runway does not generate from text here")

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=self.model, label=self.model, media_types={MediaType.VIDEO})]

    async def health(self) -> HealthResult:
        await self._call("GET", "/v1/organization")
        return HealthResult(ok=True)
