import httpx

PAGE = {"albums": {"total": 0, "count": 0, "items": [], "facets": []},
        "assets": {"total": 0, "count": 0, "items": [], "facets": [], "nextPage": None}}


def test_video_proxy_forwards_range(client, immich_mock):
    route = immich_mock.get("/api/assets/a1/video/playback").mock(return_value=httpx.Response(
        206, content=b"x" * 100,
        headers={"Content-Type": "video/mp4", "Content-Range": "bytes 0-99/1000", "Accept-Ranges": "bytes"}))
    r = client.get("/api/assets/a1/video", headers={"Range": "bytes=0-99"})
    assert route.calls[0].request.headers["range"] == "bytes=0-99"
    assert r.status_code == 206 and r.headers["content-range"] == "bytes 0-99/1000"
    assert r.headers["content-type"] == "video/mp4" and r.headers["accept-ranges"] == "bytes" and len(r.content) == 100


def test_thumb_cache_header_and_size(client, immich_mock):
    route = immich_mock.get("/api/assets/a1/thumbnail").mock(
        return_value=httpx.Response(200, content=b"img", headers={"Content-Type": "image/webp"}))
    r = client.get("/api/assets/a1/thumb?size=preview")
    assert r.status_code == 200 and r.headers["cache-control"] == "private, max-age=86400"
    assert route.calls[0].request.url.params["size"] == "preview"
    assert client.get("/api/assets/a1/thumb?size=original").status_code == 422


def test_upstream_404_passes_through(client, immich_mock):
    immich_mock.get("/api/assets/nope/thumbnail").mock(return_value=httpx.Response(404))
    assert client.get("/api/assets/nope/thumb").status_code == 404


def test_status_ok(client):
    r = client.get("/api/status").json()
    assert r == {"immich": {"ok": True, "version": "3.3.1", "user": "Quinn", "error": None}, "providers": []}


def test_old_major_sets_error_but_app_starts(make_client, immich_mock):
    immich_mock.get("/api/server/version").mock(return_value=httpx.Response(200, json={"major": 2, "minor": 9, "patch": 0}))
    with make_client() as c:
        assert c.get("/healthz").status_code == 200
        s = c.get("/api/status").json()["immich"]
        assert s["ok"] is False and "3" in s["error"]


def test_unreachable_sets_error(make_client, immich_mock):
    immich_mock.get("/api/server/version").mock(side_effect=httpx.ConnectError("boom"))
    with make_client() as c:
        s = c.get("/api/status").json()["immich"]
        assert s["ok"] is False and "reach" in s["error"]


def test_routes_require_auth(make_client):
    with make_client(APP_PASSWORD="pw") as c:
        for method, url in [("get", "/api/status"), ("get", "/api/people"), ("get", "/api/people/p/thumb"),
                            ("get", "/api/places?q=a"), ("post", "/api/search"), ("get", "/api/assets/a/thumb"),
                            ("get", "/api/assets/a/video")]:
            kw = {"json": {}} if method == "post" else {}
            assert getattr(c, method)(url, **kw).status_code == 401, url


def test_people_places_search_and_key_never_in_response(client, immich_mock):
    immich_mock.get("/api/people").mock(return_value=httpx.Response(200, json={
        "total": 2, "hidden": 0, "people": [{"id": "1", "name": ""}, {"id": "2", "name": "Ann"}]}))
    immich_mock.get("/api/search/suggestions").mock(return_value=httpx.Response(200, json=["Paris"]))
    immich_mock.post("/api/search/metadata").mock(return_value=httpx.Response(200, json=PAGE))
    immich_mock.get("/api/people/2/thumbnail").mock(return_value=httpx.Response(200, content=b"p"))
    immich_mock.get("/api/assets/boom/thumbnail").mock(return_value=httpx.Response(500, text="fake"))
    rs = [client.get("/api/status"), client.get("/api/people"), client.get("/api/people/2/thumb"),
          client.get("/api/places?q=par"), client.post("/api/search", json={}), client.get("/api/assets/boom/thumb")]
    assert [r.status_code for r in rs] == [200, 200, 200, 200, 200, 502]
    assert [p["name"] for p in rs[1].json()] == ["Ann", ""]
    assert rs[3].json()[0] == {"kind": "country", "value": "Paris"}  # the mock answers every kind
    assert rs[4].json() == {"items": [], "next_page": None}
    for r in rs:
        assert "fake" not in r.text and "fake" not in str(r.headers)
