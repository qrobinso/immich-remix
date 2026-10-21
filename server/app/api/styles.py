from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict

from ..auth import require_auth
from ..previews import estimate_preview_cost, find_preview, generate_preview, write_preview
from ..providers.base import ContentRefused, ProviderFailure
from ..styles import BUILTIN_DIR, CATEGORIES, ID_RE, StyleForm, StyleLibrary

router = APIRouter(prefix="/api/styles", dependencies=[Depends(require_auth)])


class HiddenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden: bool


class OrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: list[str]


def lib(request: Request) -> StyleLibrary:
    return request.app.state.styles


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generate: bool = False
    estimate: bool = False
    provider_id: str | None = None


MAX_UPLOAD = 10 * 1024 * 1024


def preview_dirs(sl: StyleLibrary):
    return [sl.user_dir / "previews", BUILTIN_DIR / "previews"]


def valid_id(id: str) -> str:
    if not ID_RE.match(id):
        raise HTTPException(422, "style id must match [a-z0-9_]{1,64}")
    return id


@router.get("")
def list_styles(request: Request):
    styles = lib(request).all()
    dirs = preview_dirs(lib(request))
    order = request.app.state.settings.get("styles.category_order") or []
    cats = sorted(CATEGORIES, key=lambda c: order.index(c[0]) if c[0] in order else len(order))
    return {"categories": [
        {"id": cid, "name": cname, "styles": [
            {"id": s.id, "name": s.name, "media_types": sorted(s.media_types), "preview_url": f"/api/styles/{s.id}/preview?kind=card" if find_preview(dirs, s.id) else None,
             "builtin": s.builtin, "hidden": s.hidden,
             "default_provider": {m.value: pid for m, pid in s.default_provider.items()}}
            for s in styles if s.category == cid]}
        for cid, cname in cats]}


@router.put("/{id}")
def put_style(id: str, body: HiddenBody | OrderBody | StyleForm, request: Request):
    valid_id(id)
    sl = lib(request)
    if isinstance(body, OrderBody):
        sl.set_order(body.order)
    else:
        try:
            sl.get(id)
        except KeyError:
            if isinstance(body, HiddenBody):
                raise HTTPException(404, "unknown style")
        if isinstance(body, HiddenBody):
            sl.set_hidden(id, body.hidden)
        else:
            sl.save_user(body.model_copy(update={"id": id}))
    return {"ok": True}


@router.delete("/{id}")
def delete_style(id: str, request: Request):
    valid_id(id)
    sl = lib(request)
    if sl.has_user_file(id):
        sl.delete_user(id)  # deleting an override reverts to the built-in
        return {"ok": True}
    try:
        sl.get(id)
    except KeyError:
        raise HTTPException(404, "unknown style")
    raise HTTPException(400, "built-in styles can only be hidden")


def _style(request: Request, id: str):
    valid_id(id)
    try:
        return lib(request).get(id)
    except KeyError:
        raise HTTPException(404, "unknown style")


@router.get("/{id}/preview")
def get_preview(id: str, request: Request, kind: Literal["card", "full"] = "card"):
    valid_id(id)
    p = find_preview(preview_dirs(lib(request)), id, kind)
    if not p:
        raise HTTPException(404, "no preview")
    return FileResponse(p, media_type="image/webp", headers={"Cache-Control": "max-age=86400"})


def _generator(request: Request, style, body: PreviewBody):
    st, reg = request.app.state.settings, request.app.state.providers
    pid = body.provider_id or style.default_provider.get("image") or st.get("default_provider.image")
    pid = getattr(pid, "value", pid)
    h = reg.health.get(pid) if pid else None
    try:
        p = reg.get(pid) if pid else None
    except KeyError:
        p = None
    if not (p and h and h.ok and p.can_generate):
        raise HTTPException(409, "No healthy image provider that can generate previews is configured; upload an image instead")
    return p


@router.post("/{id}/preview")
async def post_preview(id: str, request: Request):
    style = _style(request, id)
    dest = lib(request).user_dir / "previews"
    if "application/json" in request.headers.get("content-type", ""):
        try:
            body = PreviewBody.model_validate(await request.json())
        except ValueError:
            raise HTTPException(422, "invalid body")
        if not (body.generate or body.estimate):
            raise HTTPException(422, "expected generate or estimate")
        p = _generator(request, style, body)
        if body.estimate:
            return {"cost_usd": estimate_preview_cost(p)}
        try:
            data = await generate_preview(style, p)
        except ContentRefused as e:
            raise HTTPException(422, {"error_code": e.code, "message": str(e)})
        except ProviderFailure as e:
            raise HTTPException(502, {"error_code": e.code, "message": str(e)})
    else:
        form = await request.form()
        f = form.get("file")
        if f is None or isinstance(f, str):
            raise HTTPException(422, "multipart field `file` is required")
        data = await f.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "preview image must be 10 MB or smaller")
    try:
        write_preview(data, dest, id)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise HTTPException(422, "not a readable image")
    return {"preview_url": f"/api/styles/{id}/preview?kind=card"}
