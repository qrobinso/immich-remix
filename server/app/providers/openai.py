import base64

import httpx

from .base import (AuthError, ContentRefused, HealthResult, MediaType, ModelInfo, ProviderConfig, ProviderError,
                   RateLimited, RemixRequest, RemixResult, Timeout)

BASE = "https://api.openai.com/v1"
REFUSAL_CODES = {"moderation_blocked", "content_policy_violation"}


class OpenAI:
    id = "openai"
    name = "OpenAI"
    media_types = {MediaType.IMAGE}
    leaves_network = True
    max_variations = {MediaType.IMAGE: 4}
    max_input_px = 2048
    can_generate = True
    # Docs read 2026-10-21: developers.openai.com/api/docs/guides/image-generation (GPT Image 2.5 recommended for new
    # integrations; Sunburst = editing precision), /api/docs/models/gpt-image-2.5-sunburst, /api/docs/pricing.
    # Edits: POST /v1/images/edits multipart (model, prompt, image, n); generations: POST /v1/images/generations JSON.
    DEFAULT_MODEL = "gpt-image-2.5-sunburst"
    # shortcut: 2.5 has token pricing only (no static per-image table); this is the documented gpt-image-2 medium
    # 1024x1024 figure ($0.053) as a stand-in. Override with providers.openai.price_per_output.
    DEFAULTS = {"price_per_output": {"image": 0.053}, "max_video_seconds": None, "typical_seconds": None, "timeout": 180.0}

    def __init__(self, cfg: ProviderConfig, http: httpx.AsyncClient):
        self.cfg, self.http = cfg, http
        self.model = cfg.model or self.DEFAULT_MODEL
        o = {**self.DEFAULTS, **cfg.options}
        self.price_per_output, self.max_video_seconds = o["price_per_output"], o["max_video_seconds"]
        self.typical_seconds, self.timeout = o["typical_seconds"], o["timeout"]

    async def _call(self, method: str, path: str, timeout: float, **kw) -> dict:
        try:
            r = await self.http.request(method, BASE + path, headers={"Authorization": f"Bearer {self.cfg.api_key or ''}"}, timeout=timeout, **kw)
        except httpx.TimeoutException:
            raise Timeout("OpenAI timed out")
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach OpenAI ({type(e).__name__})")
        if r.is_success:
            return r.json()
        if r.status_code in (401, 403):
            raise AuthError("OpenAI rejected the API key")
        if r.status_code == 429:
            raise RateLimited("OpenAI rate limit reached")
        try:
            err = r.json()["error"]
            code, msg = err.get("code"), err.get("message") or ""
        except (ValueError, KeyError, TypeError, AttributeError):
            code, msg = None, ""
        if code in REFUSAL_CODES:
            raise ContentRefused(msg[:300] or None)
        raise ProviderError(f"OpenAI error {r.status_code}: {msg[:200]}")

    @staticmethod
    def _images(data: dict) -> list[bytes]:
        out = [base64.b64decode(d["b64_json"]) for d in data.get("data") or [] if d.get("b64_json")]
        if not out:
            raise ContentRefused("OpenAI returned no image")
        return out

    async def remix(self, req: RemixRequest) -> RemixResult:
        text = req.prompt + (f" Avoid: {req.negative_prompt}" if req.negative_prompt else "")
        n = min(req.variations, self.max_variations[MediaType.IMAGE])
        ext = "png" if "png" in req.mime else "jpg"
        data = await self._call("POST", "/images/edits", self.timeout, data={"model": self.model, "prompt": text, "n": str(n)},
                                files={"image": (f"image.{ext}", req.data, req.mime)})
        outs = self._images(data)
        price = (self.price_per_output or {}).get("image")
        return RemixResult(outputs=outs, mime="image/png", provider_model=self.model,
                           cost_estimate_usd=price * len(outs) if price is not None else None)

    async def generate(self, prompt: str) -> bytes:
        data = await self._call("POST", "/images/generations", self.timeout, json={"model": self.model, "prompt": prompt, "n": 1})
        return self._images(data)[0]

    async def list_models(self) -> list[ModelInfo]:
        data = await self._call("GET", "/models", 15)
        return [ModelInfo(id=m["id"], label=m["id"], media_types={MediaType.IMAGE}) for m in data.get("data", [])
                if "image" in m["id"] or m["id"].startswith("dall-e")]

    async def health(self) -> HealthResult:
        await self.list_models()  # failures surface as ProviderFailure; the registry turns them into a result
        return HealthResult(ok=True)
