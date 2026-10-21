from fastapi import Depends

from app.auth import require_auth


def with_ping(c):
    c.app.add_api_route("/api/_ping", lambda: {"ok": True}, dependencies=[Depends(require_auth)])
    return c


def test_wrong_password_401(make_client):
    with make_client(APP_PASSWORD="pw") as c:
        assert c.post("/api/login", json={"password": "no"}).status_code == 401


def test_sixth_attempt_429_even_if_right(make_client):
    with make_client(APP_PASSWORD="pw") as c:
        now = [0.0]
        c.app.state.auth.clock = lambda: now[0]
        for _ in range(5):
            assert c.post("/api/login", json={"password": "no"}).status_code == 401
        assert c.post("/api/login", json={"password": "pw"}).status_code == 429
        now[0] = 61
        assert c.post("/api/login", json={"password": "pw"}).status_code == 204


def test_login_cookie_flags_and_gate(make_client):
    with make_client(APP_PASSWORD="pw") as c:
        with_ping(c)
        assert c.get("/api/_ping").status_code == 401
        r = c.post("/api/login", json={"password": "pw"})
        assert r.status_code == 204
        h = r.headers["set-cookie"].lower()
        assert "remix_session=" in h and "httponly" in h and "samesite=lax" in h
        assert "max-age=2592000" in h and "secure" not in h
        assert c.get("/api/_ping").status_code == 200
        c.post("/api/logout")
        assert c.get("/api/_ping").status_code == 401


def test_forged_cookie_rejected(make_client):
    with make_client(APP_PASSWORD="pw") as c:
        with_ping(c)
        c.cookies.set("remix_session", "ok.bogus.sig")
        assert c.get("/api/_ping").status_code == 401


def test_secure_flag_behind_https_proxy(make_client):
    with make_client(APP_PASSWORD="pw") as c:
        r = c.post("/api/login", json={"password": "pw"}, headers={"x-forwarded-proto": "https"})
        assert "secure" in r.headers["set-cookie"].lower()


def test_blank_password_open(make_client):
    with make_client() as c:
        with_ping(c)
        r = c.post("/api/login", json={"password": ""})
        assert r.status_code == 204 and "set-cookie" not in r.headers
        assert c.get("/api/_ping").status_code == 200


def test_spa_fallback_does_not_shadow_late_routes(make_client, tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "sw.js").write_text("//sw")
    monkeypatch.setattr("app.main.STATIC", tmp_path)
    with make_client() as c:
        with_ping(c)
        assert c.get("/api/_ping").json() == {"ok": True}
        assert "spa" in c.get("/history").text and c.get("/sw.js").text == "//sw"
        assert c.get("/api/nope").status_code == 404 and c.get("/api/nope").headers["content-type"] == "application/json"
        assert "spa" in c.get("/../../etc/passwd").text  # traversal falls back to index, never a file outside static
