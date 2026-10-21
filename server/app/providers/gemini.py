import base64

import httpx

from .base import (AuthError, ContentRefused, HealthResult, MediaType, ModelInfo, ProviderConfig, ProviderError,
                   RateLimited, RemixRequest, RemixResult, Timeout, gather_or_cancel)

BASE = "https://generativelanguage.googleapis.com/v1beta"


class Gemini:
    id = "gemini"
    name = "Google Gemini"
    media_types = {MediaType.IMAGE}
    leaves_network = True
    max_variations = {MediaType.IMAGE: 4}
    max_input_px = 2048
    can_generate = True
    # Tuning defaults (ruling R3); each is overridable by settings key providers.gemini.<name>.
    DEFAULT_MODEL = "gemini-3.1-flash-image"
    # 1K image from ai.google.dev/gemini-api/docs/pricing, checked 2026-10-21 (0.5K 0.045, 2K 0.101, 4K 0.151)
    DEFAULTS = {"price_per_output": {"image": 0.067}, "max_video_seconds": None, "typical_seconds": None, "timeout": 180.0}

    def __init__(self, cfg: ProviderConfig, http: httpx.AsyncClient):
        self.cfg, self.http = cfg, http
        self.model = cfg.model or self.DEFAULT_MODEL
        o = {**self.DEFAULTS, **cfg.options}
        self.price_per_output, self.max_video_seconds = o["price_per_output"], o["max_video_seconds"]
        self.typical_seconds, self.timeout = o["typical_seconds"], o["timeout"]

    async def _call(self, method: str, path: str, timeout: float, **kw) -> dict:
        try:
            r = await self.http.request(method, BASE + path, headers={"x-goog-api-key": self.cfg.api_key or ""}, timeout=timeout, **kw)
        except httpx.TimeoutException:
            raise Timeout("Gemini timed out")
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Gemini ({type(e).__name__})")
        if r.is_success:
            return r.json()
        if r.status_code in (401, 403):
            raise AuthError("Gemini rejected the API key")
        if r.status_code == 429:
            raise RateLimited("Gemini rate limit reached")
        try:
            msg = r.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            msg = ""
        if "API_KEY_INVALID" in r.text:  # Google answers a malformed key with 400
            raise AuthError("Gemini rejected the API key")
        raise ProviderError(f"Gemini error {r.status_code}: {msg[:200]}")

    async def _generate_one(self, parts: list[dict]) -> tuple[bytes, str]:
        body = {"contents": [{"parts": parts}], "generationConfig": {"responseModalities": ["IMAGE"]}}
        data = await self._call("POST", f"/models/{self.model}:generateContent", self.timeout, json=body)
        cand = (data.get("candidates") or [{}])[0]
        texts = []
        for p in (cand.get("content") or {}).get("parts") or []:
            blob = p.get("inlineData") or p.get("inline_data")
            if blob and blob.get("data"):
                return base64.b64decode(blob["data"]), blob.get("mimeType") or blob.get("mime_type") or "image/png"
            if p.get("text"):
                texts.append(p["text"])
        reason = (data.get("promptFeedback") or {}).get("blockReason") or cand.get("finishReason")
        raise ContentRefused(" ".join(texts) or (f"Blocked: {reason}" if reason else None))

    async def remix(self, req: RemixRequest) -> RemixResult:
        text = req.prompt + (f" Avoid: {req.negative_prompt}" if req.negative_prompt else "")
        parts = [{"inline_data": {"mime_type": req.mime, "data": base64.b64encode(req.data).decode()}}, {"text": text}]
        got = await gather_or_cancel([self._generate_one(parts) for _ in range(req.variations)])
        price = (self.price_per_output or {}).get("image")
        return RemixResult(outputs=[g[0] for g in got], mime=got[0][1], provider_model=self.model,
                           cost_estimate_usd=price * len(got) if price is not None else None)

    async def generate(self, prompt: str) -> bytes:
        return (await self._generate_one([{"text": prompt}]))[0]

    async def list_models(self) -> list[ModelInfo]:
        data = await self._call("GET", "/models", 15, params={"pageSize": 200})
        out = []
        for m in data.get("models", []):
            id = m["name"].removeprefix("models/")
            if "image" in id:
                out.append(ModelInfo(id=id, label=f"{m.get('displayName', id)} · {id}", media_types={MediaType.IMAGE}))
        return out

    async def health(self) -> HealthResult:
        await self.list_models()  # failures surface as ProviderFailure; the registry turns them into a result
        return HealthResult(ok=True)
