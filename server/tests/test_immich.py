import json
from datetime import date, datetime

import httpx
import pytest

from app.immich import Immich, Place, SearchQuery

BASE = "http://immich.test"


@pytest.fixture
def im():
    return Immich(BASE, "secret-key")


def asset(i, type="IMAGE", w=300, h=200, **kw):
    return {
        "id": i, "type": type, "thumbhash": "th", "localDateTime": "2024-05-01T10:00:00.000Z",
        "fileCreatedAt": "2024-05-01T10:00:00.000Z", "duration": 4500 if type == "VIDEO" else None,
        "width": w, "height": h, "originalFileName": f"{i}.jpg", **kw,
    }


def page(items, next_page=None):
    return {"albums": {"total": 0, "count": 0, "items": [], "facets": []},
            "assets": {"total": len(items), "count": len(items), "items": items, "facets": [], "nextPage": next_page}}


async def test_text_query_uses_smart_search(im, immich_mock):
    route = immich_mock.post("/api/search/smart").mock(
        return_value=httpx.Response(200, json=page([asset("a1", "VIDEO")], "2")))
    q = SearchQuery(query="beach", person_ids=["p1"], place=Place(kind="city", value="Paris"), type="video", page=1)
    res = await im.search(q)
    assert json.loads(route.calls[0].request.content) == {
        "query": "beach", "type": "VIDEO", "personIds": ["p1"], "city": "Paris", "page": 1, "size": 100}
    assert route.calls[0].request.headers["x-api-key"] == "secret-key"
    card = res.items[0]
    assert (card.id, card.type, card.duration_s, card.ratio, card.thumbhash) == ("a1", "video", 4.5, 1.5, "th")
    assert res.next_page == 2


async def test_no_query_uses_metadata_desc(im, immich_mock):
    route = immich_mock.post("/api/search/metadata").mock(
        return_value=httpx.Response(200, json=page([asset("a1")], None)))
    q = SearchQuery(date_from=date(2024, 1, 1), date_to=date(2024, 1, 31), page=3)
    res = await im.search(q)
    assert json.loads(route.calls[0].request.content) == {
        "order": "desc", "takenAfter": "2024-01-01T00:00:00.000Z", "takenBefore": "2024-01-31T23:59:59.999Z",
        "page": 3, "size": 100}
    assert res.items[0].type == "photo" and res.next_page is None


async def test_search_drops_non_media(im, immich_mock):
    immich_mock.post("/api/search/metadata").mock(
        return_value=httpx.Response(200, json=page([asset("a1"), asset("a2", "AUDIO")])))
    assert [c.id for c in (await im.search(SearchQuery())).items] == ["a1"]


async def test_people_named_first(im, immich_mock):
    route = immich_mock.get("/api/people").mock(return_value=httpx.Response(200, json={
        "total": 4, "hidden": 0, "people": [{"id": "1", "name": ""}, {"id": "2", "name": "Ann"},
                                            {"id": "3", "name": ""}, {"id": "4", "name": "Bob"}]}))
    ps = await im.people(2)
    assert [p.id for p in ps] == ["2", "4", "1", "3"]
    assert dict(route.calls[0].request.url.params) == {"page": "2", "size": "100", "withHidden": "false"}


async def test_places_filter_and_cap(im, immich_mock):
    immich_mock.get("/api/search/suggestions", params={"type": "country"}).mock(
        return_value=httpx.Response(200, json=["France", "Japan"]))
    immich_mock.get("/api/search/suggestions", params={"type": "state"}).mock(
        return_value=httpx.Response(200, json=["Normandy"]))
    cities = [f"Cityville{i}" for i in range(80)]
    r = immich_mock.get("/api/search/suggestions", params={"type": "city"}).mock(
        return_value=httpx.Response(200, json=cities + ["Paris"]))
    out = await im.places("fRa")
    assert [(p.kind, p.value) for p in out] == [("country", "France")]
    assert len(await im.places("city")) == 50
    assert await im.places("pari") == [Place(kind="city", value="Paris")]
    assert r.call_count == 1  # cached


async def test_places_cache_expires(im, immich_mock, monkeypatch):
    r = immich_mock.get("/api/search/suggestions").mock(return_value=httpx.Response(200, json=["X"]))
    t = [1000.0]
    monkeypatch.setattr("app.immich.time.monotonic", lambda: t[0])
    await im.places("x")
    t[0] += 601
    await im.places("x")
    assert r.call_count == 6


async def test_upload_duplicate_returns_existing_id(im, immich_mock):
    route = immich_mock.post("/api/assets").mock(
        return_value=httpx.Response(200, json={"status": "duplicate", "id": "existing"}))
    got = await im.upload(b"jpgdata", "r.jpg", "dev1", datetime(2024, 5, 1, 10, 0))
    assert got == "existing"
    req = route.calls[0].request
    assert req.headers["content-type"].startswith("multipart/form-data")
    assert b'name="assetData"; filename="r.jpg"' in req.content and b"2024-05-01T10:00:00.000Z" in req.content


async def test_upload_created(im, immich_mock):
    immich_mock.post("/api/assets").mock(return_value=httpx.Response(201, json={"status": "created", "id": "new"}))
    assert await im.upload(b"x", "r.jpg", "d", datetime(2024, 5, 1)) == "new"


async def test_update_assets_and_stack(im, immich_mock):
    u = immich_mock.put("/api/assets").mock(return_value=httpx.Response(204))
    s = immich_mock.post("/api/stacks").mock(return_value=httpx.Response(201, json={"id": "st", "primaryAssetId": "a", "assets": []}))
    await im.update_assets(["a"], dateTimeOriginal="2024-05-01T10:00:00.000Z", latitude=1.5, description="d")
    assert json.loads(u.calls[0].request.content) == {
        "ids": ["a"], "dateTimeOriginal": "2024-05-01T10:00:00.000Z", "latitude": 1.5, "description": "d"}
    assert await im.create_stack(["a", "b"]) == "st"
    assert json.loads(s.calls[0].request.content) == {"assetIds": ["a", "b"]}


async def test_album_find_or_create(im, immich_mock):
    immich_mock.get("/api/albums").mock(return_value=httpx.Response(200, json=[{"id": "al1", "albumName": "Remixes"}]))
    assert await im.find_or_create_album("Remixes") == "al1"
    c = immich_mock.post("/api/albums").mock(return_value=httpx.Response(201, json={"id": "al2", "albumName": "New"}))
    assert await im.find_or_create_album("New") == "al2"
    assert json.loads(c.calls[0].request.content) == {"albumName": "New"}
    p = immich_mock.put("/api/albums/al1/assets").mock(return_value=httpx.Response(200, json=[]))
    await im.add_to_album("al1", ["a"])
    assert json.loads(p.calls[0].request.content) == {"ids": ["a"]}


async def test_tag_find_or_create(im, immich_mock):
    immich_mock.get("/api/tags").mock(return_value=httpx.Response(200, json=[{"id": "t1", "name": "remix", "value": "remix"}]))
    assert await im.find_or_create_tag("remix") == "t1"
    c = immich_mock.post("/api/tags").mock(return_value=httpx.Response(201, json={"id": "t2", "name": "n", "value": "n"}))
    assert await im.find_or_create_tag("n") == "t2"
    assert json.loads(c.calls[0].request.content) == {"name": "n"}
    p = immich_mock.put("/api/tags/t1/assets").mock(return_value=httpx.Response(200, json=[]))
    await im.tag_assets("t1", ["a"])
    assert json.loads(p.calls[0].request.content) == {"ids": ["a"]}


async def test_asset_original_preview_version_me(im, immich_mock):
    immich_mock.get("/api/assets/a").mock(return_value=httpx.Response(200, json={"id": "a"}))
    immich_mock.get("/api/assets/a/original").mock(return_value=httpx.Response(200, content=b"orig"))
    pv = immich_mock.get("/api/assets/a/thumbnail").mock(return_value=httpx.Response(200, content=b"prev"))
    assert (await im.asset("a"))["id"] == "a"
    assert await im.original("a") == b"orig"
    assert await im.preview("a") == b"prev"
    assert pv.calls[0].request.url.params["size"] == "preview"
    assert await im.version() == (3, 3, 1)
    assert (await im.me())["name"] == "Quinn"
