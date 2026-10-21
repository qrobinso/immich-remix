import asyncio

import httpx

from ..db import Settings
from .base import HealthResult, MediaType, Provider, ProviderConfig, ProviderFailure
from .comfyui import ComfyUI
from .gemini import Gemini
from .luma import Luma
from .openai import OpenAI
from .runway import Runway
from .stability import Stability

PROVIDER_CLASSES: dict[str, type] = {"gemini": Gemini, "openai": OpenAI, "stability": Stability, "runway": Runway, "luma": Luma, "comfyui": ComfyUI}
TUNING = ("price_per_output", "max_video_seconds", "typical_seconds", "timeout", "poll_interval")


class Registry:
    def __init__(self, settings: Settings, http: httpx.AsyncClient):
        self.settings, self.http = settings, http
        self.health: dict[str, HealthResult] = {}

    def _build(self, id: str) -> Provider:
        g = lambda n: self.settings.get(f"providers.{id}.{n}")
        opts = {n: v for n in TUNING if (v := g(n)) is not None}
        if id == "comfyui":  # user workflow templates live in <DATA_DIR>/workflows
            opts["data_dir"] = self.settings.env.DATA_DIR
        return PROVIDER_CLASSES[id](ProviderConfig(api_key=g("api_key"), model=g("model"), url=g("url"), options=opts), self.http)

    def enabled(self) -> list[Provider]:  # rebuilt each call so settings changes apply at once
        return [self._build(i) for i in PROVIDER_CLASSES if self.settings.get(f"providers.{i}.enabled")]

    def get(self, id: str) -> Provider:
        if id not in PROVIDER_CLASSES:
            raise KeyError(id)
        return self._build(id)

    def for_media(self, mt: MediaType) -> list[Provider]:
        return [p for p in self.enabled() if mt in p.media_types and (h := self.health.get(p.id)) and h.ok]

    async def _check(self, p: Provider) -> tuple[str, HealthResult]:
        try:
            return p.id, await asyncio.wait_for(p.health(), 10)
        except ProviderFailure as e:
            return p.id, HealthResult(ok=False, message=str(e))
        except asyncio.TimeoutError:
            return p.id, HealthResult(ok=False, message="Health check timed out")
        except Exception as e:  # generic: never echo details that could carry a key
            return p.id, HealthResult(ok=False, message=f"Health check failed ({type(e).__name__})")

    async def refresh_health(self) -> None:
        self.health = dict(await asyncio.gather(*[self._check(p) for p in self.enabled()]))
