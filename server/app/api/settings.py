import re
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth import require_auth
from ..db import PROVIDERS, ReadOnlySetting
from ..providers.base import ModelInfo, ProviderFailure
from ..providers.registry import PROVIDER_CLASSES, TUNING
from ..styles import CATEGORIES
from .library import immich

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])


def _int(lo, hi):
    return lambda v: type(v) is int and lo <= v <= hi


def _str(lo, hi, nullable=True):
    return lambda v: (v is None and nullable) or (isinstance(v, str) and lo <= len(v) <= hi)


def _provider_id_or_null(v):
    return v is None or v in PROVIDERS


def _categories(v):
    ids = [c[0] for c in CATEGORIES]
    return v is None or (isinstance(v, list) and len(set(v)) == len(v) and all(x in ids for x in v))


def _url(v):
    return v is None or (isinstance(v, str) and re.fullmatch(r"https?://\S+", v) is not None)


def _number(v):
    return type(v) in (int, float) and v >= 0


RULES: dict[str, Any] = {
    "photo.max_px": _int(256, 8192),
    "photo.jpeg_quality": _int(50, 100),
    "photo.source": lambda v: v in ("original", "preview"),
    "video.max_height": lambda v: type(v) is int and v in (480, 720, 1080, 1440, 2160),
    "video.keep_audio": lambda v: isinstance(v, bool),
    "cleanup.days": _int(1, 365),
    "save.stack_primary": lambda v: v in ("original", "remix"),
    "save.album": _str(1, 100),
    "save.tag": _str(1, 50),
    "default_provider.image": _provider_id_or_null,
    "default_provider.video": _provider_id_or_null,
    "styles.category_order": _categories,
}
for _p in PROVIDERS:
    RULES[f"providers.{_p}.enabled"] = lambda v: isinstance(v, bool)
    RULES[f"providers.{_p}.api_key"] = _str(0, 4096, nullable=False)
    RULES[f"providers.{_p}.model"] = _str(1, 200)
    if _p == "comfyui":
        RULES[f"providers.{_p}.url"] = _url
    for _t in TUNING:
        RULES[f"providers.{_p}.{_t}"] = _number


def _provider(request: Request, id: str):
    if id not in PROVIDER_CLASSES:
        raise HTTPException(404, "Unknown provider")
    return request.app.state.providers.get(id)


@router.get("/settings")
async def get_settings(request: Request):
    st, reg = request.app.state.settings, request.app.state.providers
    values = st.public()
    out = []
    for id, cls in PROVIDER_CLASSES.items():
        inst = reg.get(id)
        h = reg.health.get(id)
        out.append({
            "id": id, "name": inst.name, "media_types": sorted(inst.media_types),
            "enabled": bool(st.get(f"providers.{id}.enabled")), "healthy": bool(h and h.ok), "message": h.message if h else None,
            "key_set": bool(st.get(f"providers.{id}.api_key")), "key_source": st.source(f"providers.{id}.api_key"),
            "model": st.get(f"providers.{id}.model") or getattr(cls, "DEFAULT_MODEL", None),
            "url": st.get(f"providers.{id}.url"),
        })
    return {"values": values, "sources": {k: st.source(k) for k in values}, "providers": out}


@router.put("/settings")
async def put_settings(body: dict, request: Request):
    st = request.app.state.settings
    for k, v in body.items():
        if k not in RULES or not RULES[k](v):
            raise HTTPException(422, f"Invalid setting or value: {k}")
    for k in body:
        if st.source(k) == "env":
            raise HTTPException(409, f"{k} is set by the environment and cannot be changed here")
    try:
        for k, v in body.items():
            st.set(k, v)
    except ReadOnlySetting as e:
        raise HTTPException(409, f"{e} is set by the environment and cannot be changed here")
    if any(k.startswith("providers.") for k in body):
        await request.app.state.providers.refresh_health()
    return {"ok": True}


@router.post("/providers/{id}/test")
async def test_provider(id: str, request: Request):
    _provider(request, id)  # 404 for unknown ids
    return await request.app.state.providers.check(id)


@router.get("/providers/{id}/models")
async def provider_models(id: str, request: Request) -> list[ModelInfo] | dict:
    p = _provider(request, id)
    try:
        return await p.list_models()
    except (ProviderFailure, httpx.HTTPError):
        return {"error": "Could not list models; enter a model id manually", "fallback": True}


@router.get("/albums")
async def albums(request: Request) -> list[dict]:
    try:
        return await immich(request).albums()
    except httpx.HTTPError:
        raise HTTPException(502, "Immich albums failed")
