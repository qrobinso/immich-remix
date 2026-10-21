import time
from datetime import date, datetime
from typing import Literal

import httpx
from pydantic import BaseModel

PLACES_TTL = 600
PLACES_MAX = 50
_TYPES = {"photo": "IMAGE", "video": "VIDEO"}


class Place(BaseModel):
    kind: Literal["city", "state", "country"]
    value: str


class Person(BaseModel):
    id: str
    name: str


class AssetCard(BaseModel):
    id: str
    type: Literal["photo", "video"]
    taken_at: datetime
    ratio: float
    duration_s: float | None = None
    thumbhash: str | None = None
    alt: str | None = None


class SearchPage(BaseModel):
    items: list[AssetCard]
    next_page: int | None = None


class SearchQuery(BaseModel):
    query: str | None = None
    person_ids: list[str] = []
    place: Place | None = None
    date_from: date | None = None
    date_to: date | None = None
    type: Literal["all", "photo", "video"] = "all"
    page: int = 1
    size: int = 100


def _card(a: dict) -> AssetCard | None:
    if a["type"] not in ("IMAGE", "VIDEO"):
        return None
    w, h = a.get("width"), a.get("height")
    dur = a.get("duration")
    return AssetCard(
        id=a["id"],
        type="video" if a["type"] == "VIDEO" else "photo",  # live photos arrive as IMAGE
        taken_at=a.get("localDateTime") or a["fileCreatedAt"],
        ratio=w / h if w and h else 1.0,
        duration_s=dur / 1000 if dur else None,
        thumbhash=a.get("thumbhash"),
        alt=(a.get("exifInfo") or {}).get("description") or None,
    )


class Immich:
    def __init__(self, base_url: str, api_key: str, client: httpx.AsyncClient | None = None):
        # The key lives only in the client's default headers.
        self.http = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/") + "/api", headers={"x-api-key": api_key}, timeout=30
        )
        self._places: tuple[float, list[Place]] | None = None

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _req(self, method: str, path: str, **kw):
        r = await self.http.request(method, path, **kw)
        r.raise_for_status()
        return r

    async def _json(self, method: str, path: str, **kw):
        return (await self._req(method, path, **kw)).json()

    async def version(self) -> tuple[int, int, int]:
        v = await self._json("GET", "/server/version")
        return v["major"], v["minor"], v["patch"]

    async def me(self) -> dict:
        return await self._json("GET", "/users/me")

    async def search(self, q: SearchQuery) -> SearchPage:
        body: dict = {}
        if not q.query:
            body["order"] = "desc"
        else:
            body["query"] = q.query
        if q.type != "all":
            body["type"] = _TYPES[q.type]
        if q.person_ids:
            body["personIds"] = q.person_ids
        if q.place:
            body[q.place.kind] = q.place.value
        if q.date_from:
            body["takenAfter"] = f"{q.date_from.isoformat()}T00:00:00.000Z"
        if q.date_to:
            body["takenBefore"] = f"{q.date_to.isoformat()}T23:59:59.999Z"
        body |= {"page": q.page, "size": q.size}
        data = await self._json("POST", "/search/smart" if q.query else "/search/metadata", json=body)
        assets = data["assets"]
        nxt = assets.get("nextPage")
        return SearchPage(
            items=[c for a in assets["items"] if (c := _card(a))],
            next_page=int(nxt) if nxt else None,
        )

    async def people(self, page: int, size: int = 100) -> list[Person]:
        data = await self._json("GET", "/people", params={"page": page, "size": size, "withHidden": "false"})
        ps = [Person(id=p["id"], name=p.get("name") or "") for p in data["people"]]
        return [p for p in ps if p.name] + [p for p in ps if not p.name]

    async def places(self, q: str) -> list[Place]:
        now = time.monotonic()
        if not self._places or now - self._places[0] > PLACES_TTL:
            allp = []
            for kind in ("country", "state", "city"):
                vals = await self._json("GET", "/search/suggestions", params={"type": kind})
                allp += [Place(kind=kind, value=v) for v in vals if v]
            self._places = (now, allp)
        q = q.lower()
        return [p for p in self._places[1] if q in p.value.lower()][:PLACES_MAX]

    async def stream(self, path: str, headers: dict) -> httpx.Response:
        """Streaming GET; the caller must aclose() the response."""
        return await self.http.send(self.http.build_request("GET", path, headers=headers), stream=True)

    async def asset(self, id: str) -> dict:
        return await self._json("GET", f"/assets/{id}")

    async def original(self, id: str) -> bytes:
        return (await self._req("GET", f"/assets/{id}/original")).content

    async def preview(self, id: str) -> bytes:
        return (await self._req("GET", f"/assets/{id}/thumbnail", params={"size": "preview"})).content

    async def upload(self, data: bytes, filename: str, device_asset_id: str, created_at: datetime) -> str:
        # v3 has no deviceId/deviceAssetId fields (spec checked), so device_asset_id is unused; kept for the agreed interface.
        ts = created_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        form = {"fileCreatedAt": ts, "fileModifiedAt": ts, "filename": filename}
        r = await self._json("POST", "/assets", data=form, files={"assetData": (filename, data)})
        return r["id"]  # same id for status "created" and "duplicate"

    async def update_assets(self, ids: list[str], **fields) -> None:
        """fields use Immich's names: dateTimeOriginal, latitude, longitude, description, timeZone."""
        await self._req("PUT", "/assets", json={"ids": ids, **fields})

    async def create_stack(self, asset_ids: list[str]) -> str:
        return (await self._json("POST", "/stacks", json={"assetIds": asset_ids}))["id"]

    async def find_or_create_album(self, name: str) -> str:
        for a in await self._json("GET", "/albums"):
            if a["albumName"] == name:
                return a["id"]
        return (await self._json("POST", "/albums", json={"albumName": name}))["id"]

    async def add_to_album(self, album_id: str, ids: list[str]) -> None:
        await self._req("PUT", f"/albums/{album_id}/assets", json={"ids": ids})

    async def find_or_create_tag(self, name: str) -> str:
        for t in await self._json("GET", "/tags"):
            if t["name"] == name or t["value"] == name:
                return t["id"]
        return (await self._json("POST", "/tags", json={"name": name}))["id"]

    async def tag_assets(self, tag_id: str, ids: list[str]) -> None:
        await self._req("PUT", f"/tags/{tag_id}/assets", json={"ids": ids})
