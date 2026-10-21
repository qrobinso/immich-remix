from enum import Enum
from typing import Protocol

import httpx
from pydantic import BaseModel


class MediaType(str, Enum):
    IMAGE = "image"
    VIDEO = "video"


class RemixRequest(BaseModel):
    media_type: MediaType
    data: bytes  # JPEG/PNG, or H.264 MP4; already normalized
    mime: str
    prompt: str  # final prompt built from the style preset
    negative_prompt: str | None
    strength: float | None  # 0..1, how far from the original; ignored if unsupported
    variations: int
    seed: int | None
    style_reference: bytes | None  # optional reference image from the preset
    options: dict  # provider-specific overrides from the style preset


class RemixResult(BaseModel):
    outputs: list[bytes]
    mime: str
    provider_model: str  # the exact model id used, stored in history
    cost_estimate_usd: float | None


class ModelInfo(BaseModel):
    id: str
    label: str
    media_types: set[MediaType]


class HealthResult(BaseModel):
    ok: bool
    message: str | None = None


class ProviderConfig(BaseModel):
    api_key: str | None
    model: str | None
    url: str | None
    options: dict  # tuning overrides from settings: price_per_output, max_video_seconds, typical_seconds, timeout


class ProviderFailure(Exception):
    code = "provider_error"

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)


class AuthError(ProviderFailure):
    code = "auth"


class RateLimited(ProviderFailure):
    code = "rate_limited"


class Timeout(ProviderFailure):
    code = "timeout"


class ProviderError(ProviderFailure):
    code = "provider_error"


class ContentRefused(ProviderFailure):
    code = "content_refused"

    def __init__(self, reason: str | None = None):
        self.reason = reason
        super().__init__(reason or "The model refused this content")


class Provider(Protocol):
    id: str  # "gemini", "openai", "stability", "runway", "luma", "comfyui"
    name: str  # shown in the UI
    media_types: set[MediaType]  # what this backend can remix
    leaves_network: bool  # drives the "Sent to Google" / "Runs locally" note
    max_variations: dict[MediaType, int]
    max_input_px: int  # long edge; the runner resizes before calling
    max_video_seconds: float | None  # clip limit; the runner trims or segments to fit
    price_per_output: dict[str, float] | None  # {"image": usd, "video": usd}, for cost estimates
    can_generate: bool

    def __init__(self, cfg: ProviderConfig, http: httpx.AsyncClient): ...
    async def health(self) -> HealthResult: ...
    async def remix(self, req: RemixRequest) -> RemixResult: ...
    async def generate(self, prompt: str) -> bytes: ...
    async def list_models(self) -> list[ModelInfo]: ...
