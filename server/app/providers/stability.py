import httpx

from .base import (AuthError, ContentRefused, HealthResult, MediaType, ModelInfo, ProviderConfig, ProviderError,
                   RateLimited, RemixRequest, RemixResult, Timeout)

BASE = "https://api.stability.ai"


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class Stability:
    id = "stability"
    name = "Stability AI"
    media_types = {MediaType.IMAGE}
    leaves_network = True
    max_variations = {MediaType.IMAGE: 4}
    max_input_px = 2048
    can_generate = True
    # Docs read 2026-10-21 (docs.stability.ai/llms.txt index):
    #   /api-reference/control/style-transfer.md  POST /v2beta/stable-image/control/style-transfer  init_image, style_image, change_strength 0.1-1; 8 credits
    #   /api-reference/control/structure.md       POST /v2beta/stable-image/control/structure       image, prompt, control_strength 0-1 (default 0.7),
    #       negative_prompt, seed, output_format png|jpeg|webp; 5 credits; output keeps the input's structure and size
    #       (read 2026-10-21, https://docs.stability.ai/api-reference/control/structure.md). control/style is not used:
    #       it treats `image` as the style guide, so the photo's people and composition were lost.
    #   /api-reference/generate/stable-image-core.md  POST /v2beta/stable-image/generate/core      prompt; 3 credits
    #   /api-reference/user/account-balance.md    GET /v1/user/balance -> {"credits": n}   (health check; spends nothing)
    #   /pricing.md  1 credit = $0.01. Errors: 403 moderated, 422 rejected (public figure etc.), 402 no credits.
    ENDPOINTS = {  # configured model id -> (path, USD per image)
        "style-transfer": ("/v2beta/stable-image/control/style-transfer", 0.08),
        "control/structure": ("/v2beta/stable-image/control/structure", 0.05),
    }
    DEFAULT_MODEL = "auto"  # style-transfer when the preset has a style image, else control/structure
    DEFAULTS = {"price_per_output": None, "max_video_seconds": None, "typical_seconds": None, "timeout": 180.0}

    def __init__(self, cfg: ProviderConfig, http: httpx.AsyncClient):
        self.cfg, self.http = cfg, http
        self.model = cfg.model or self.DEFAULT_MODEL
        o = {**self.DEFAULTS, **cfg.options}
        self.price_per_output, self.max_video_seconds = o["price_per_output"] or {"image": 0.08}, o["max_video_seconds"]
        self.typical_seconds, self.timeout = o["typical_seconds"], o["timeout"]
        self._custom_price = o["price_per_output"] is not None

    async def _post(self, path: str, data: dict, files: dict) -> tuple[bytes, str]:
        try:
            r = await self.http.post(BASE + path, headers={"Authorization": f"Bearer {self.cfg.api_key or ''}", "Accept": "image/*"},
                                     data=data, files=files, timeout=self.timeout)
        except httpx.TimeoutException:
            raise Timeout("Stability timed out")
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Stability ({type(e).__name__})")
        if r.is_success:
            if r.headers.get("finish-reason") == "CONTENT_FILTERED":
                raise ContentRefused("Stability's content filter blurred the result")
            return r.content, r.headers.get("content-type", "image/png").split(";")[0]
        if r.status_code == 401:
            raise AuthError("Stability rejected the API key")
        if r.status_code == 429:
            raise RateLimited("Stability rate limit reached")
        try:
            body = r.json()
            msg = "; ".join(map(str, body.get("errors") or [])) or body.get("name") or ""
        except (ValueError, AttributeError):
            msg = ""
        if r.status_code in (403, 422):  # 403 moderation; 422 rejected input (public figure, non-English prompt)
            raise ContentRefused(msg[:300] or None)
        if r.status_code == 402:
            raise ProviderError("Stability account is out of credits")
        raise ProviderError(f"Stability error {r.status_code}: {msg[:200]}")

    async def remix(self, req: RemixRequest) -> RemixResult:
        # style-transfer needs a style image; without one, structure control keeps the photo's people and composition
        endpoint = "style-transfer" if req.style_reference and self.model != "control/structure" else "control/structure"
        path, usd = self.ENDPOINTS[endpoint]
        structure = endpoint == "control/structure"
        form = {"prompt": req.prompt}
        if req.negative_prompt:
            form["negative_prompt"] = req.negative_prompt
        if req.strength is not None:  # higher strength = further from the original
            form.update({"control_strength": str(_clamp(round(1 - req.strength, 4), 0, 1))} if structure else {"change_strength": str(_clamp(req.strength, 0.1, 1))})
        if structure:
            form["output_format"] = "png"
            files = {"image": ("image", req.data, req.mime)}
        else:
            files = {"init_image": ("image", req.data, req.mime), "style_image": ("style", req.style_reference, "application/octet-stream")}
        outs, mime = [], "image/png"
        for i in range(req.variations):  # one call per variation; sequential keeps us under the rate limit
            f = {**form, **({"seed": str(req.seed + i)} if req.seed is not None else {})}
            data, mime = await self._post(path, f, files)
            outs.append(data)
        price = (self.price_per_output["image"] if self._custom_price else usd)
        return RemixResult(outputs=outs, mime=mime, provider_model=endpoint, cost_estimate_usd=price * len(outs))

    async def generate(self, prompt: str) -> bytes:
        return (await self._post("/v2beta/stable-image/generate/core", {"prompt": prompt}, {"none": ("", b"")}))[0]

    async def list_models(self) -> list[ModelInfo]:  # no list API: the configured endpoint choices
        return [ModelInfo(id=k, label=k, media_types={MediaType.IMAGE}) for k in self.ENDPOINTS]

    async def health(self) -> HealthResult:
        try:
            r = await self.http.get(BASE + "/v1/user/balance", headers={"Authorization": f"Bearer {self.cfg.api_key or ''}"}, timeout=15)
        except httpx.TimeoutException:
            raise Timeout("Stability timed out")
        except httpx.HTTPError as e:
            raise ProviderError(f"Cannot reach Stability ({type(e).__name__})")
        if r.status_code == 401:
            raise AuthError("Stability rejected the API key")
        if not r.is_success:
            raise ProviderError(f"Stability error {r.status_code}")
        return HealthResult(ok=True)
