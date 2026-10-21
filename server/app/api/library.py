from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from ..auth import require_auth
from ..immich import Immich, Person, Place, SearchPage, SearchQuery

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])

PASS = ("content-type", "content-length", "content-range", "accept-ranges")


def immich(request: Request) -> Immich:
    return request.app.state.immich


async def check_immich(app) -> None:
    """Sets app.state.immich_error (None when healthy) and immich_version/immich_user."""
    app.state.immich_version = app.state.immich_user = None
    try:
        v = await app.state.immich.version()
        if v[0] < 3:
            app.state.immich_error = f"Immich {'.'.join(map(str, v))} is too old; Immich 3 or newer is required"
            return
        app.state.immich_version = ".".join(map(str, v))
        app.state.immich_user = (await app.state.immich.me()).get("name")
        app.state.immich_error = None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:  # generic message: never echo request details; ValueError covers bad JSON
        status = getattr(getattr(e, "response", None), "status_code", None)
        app.state.immich_error = f"Immich rejected the request ({status})" if status else "Cannot reach Immich"


async def proxy(im: Immich, request: Request, path: str, cache: bool = False) -> StreamingResponse:
    headers = {"range": request.headers["range"]} if "range" in request.headers else {}
    try:
        up = await im.stream(path, headers)
    except httpx.HTTPError:
        raise HTTPException(502, "Cannot reach Immich")
    if up.status_code not in (200, 206):
        await up.aclose()
        raise HTTPException(404 if up.status_code == 404 else 502, "Immich could not serve this")
    h = {k: up.headers[k] for k in PASS if k in up.headers}
    if cache:
        h["cache-control"] = "private, max-age=86400"
    return StreamingResponse(up.aiter_raw(), status_code=up.status_code, headers=h, background=BackgroundTask(up.aclose))


def provider_status(p, h) -> dict:
    return {
        "id": p.id, "name": p.name, "media_types": sorted(p.media_types), "leaves_network": p.leaves_network,
        "healthy": bool(h and h.ok), "message": h.message if h else None, "price_per_output": p.price_per_output,
    }


@router.get("/status")
async def status(request: Request):
    await check_immich(request.app)
    s = request.app.state
    return {
        "immich": {"ok": s.immich_error is None, "version": s.immich_version, "user": s.immich_user, "error": s.immich_error},
        "providers": [provider_status(p, s.providers.health.get(p.id)) for p in s.providers.enabled()],
    }


@router.get("/people")
async def people(request: Request, page: int = 1) -> list[Person]:
    return await immich(request).people(page)


@router.get("/people/{id}/thumb")
async def person_thumb(id: str, request: Request):
    return await proxy(immich(request), request, f"/people/{id}/thumbnail", cache=True)


@router.get("/places")
async def places(request: Request, q: str = "") -> list[Place]:
    return await immich(request).places(q)


@router.post("/search")
async def search(q: SearchQuery, request: Request) -> SearchPage:
    try:
        return await immich(request).search(q)
    except httpx.HTTPError:
        raise HTTPException(502, "Immich search failed")


@router.get("/assets/{id}/thumb")
async def asset_thumb(id: str, request: Request, size: Literal["thumbnail", "preview"] = "thumbnail"):
    return await proxy(immich(request), request, f"/assets/{id}/thumbnail?size={size}", cache=True)


@router.get("/assets/{id}/video")
async def asset_video(id: str, request: Request):
    return await proxy(immich(request), request, f"/assets/{id}/video/playback")
