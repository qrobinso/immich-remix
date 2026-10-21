import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from ..auth import require_auth
from ..styles import CATEGORIES, ID_RE, StyleForm, StyleLibrary

router = APIRouter(prefix="/api/styles", dependencies=[Depends(require_auth)])


class HiddenBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hidden: bool


class OrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: list[str]


def lib(request: Request) -> StyleLibrary:
    return request.app.state.styles


def valid_id(id: str) -> str:
    if not ID_RE.match(id):
        raise HTTPException(422, "style id must match [a-z0-9_]{1,64}")
    return id


@router.get("")
def list_styles(request: Request):
    styles = lib(request).all()
    order = request.app.state.settings.get("styles.category_order") or []
    cats = sorted(CATEGORIES, key=lambda c: order.index(c[0]) if c[0] in order else len(order))
    return {"categories": [
        {"id": cid, "name": cname, "styles": [
            {"id": s.id, "name": s.name, "media_types": sorted(s.media_types), "preview_url": None,  # Task 15
             "builtin": s.builtin, "hidden": s.hidden}
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
