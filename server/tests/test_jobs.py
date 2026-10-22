import asyncio
import io
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from PIL import Image

from app.api import jobs as jobs_api
from app.db import connect
from app.jobs import cleanup_results
from app.providers import registry
from app.providers.base import ContentRefused, HealthResult, MediaType, RateLimited, RemixResult


def jpeg(color="red", size=(64, 48)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "JPEG")
    return out.getvalue()


def png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (32, 24), "blue").save(out, "PNG")
    return out.getvalue()


def make_fake(pid: str, media: MediaType, cap: int, max_s: float | None = None):
    class Fake:
        id, name, media_types, leaves_network = pid, f"Fake {pid}", {media}, False
        max_variations, max_input_px, max_video_seconds = {media: cap}, 2048, max_s
        price_per_output, can_generate, timeout, typical_seconds = None, False, 5.0, 42.0
        script: list = []  # exceptions raised by successive calls
        calls: list = []
        active = peak = 0
        delay = 0.0

        def __init__(self, cfg, http):
            pass

        async def health(self):
            return HealthResult(ok=True)

        async def remix(self, req):
            F = type(self)
            F.calls.append(req)
            F.active += 1
            F.peak = max(F.peak, F.active)
            try:
                await asyncio.sleep(F.delay)
                if F.script:
                    raise F.script.pop(0)
                out = req.data if media is MediaType.VIDEO else png()
                return RemixResult(outputs=[out] * req.variations, mime="video/mp4" if media is MediaType.VIDEO else "image/png",
                                   provider_model="fake-1", cost_estimate_usd=0.1)
            finally:
                F.active -= 1

    return Fake


@pytest.fixture
def fakes(monkeypatch):
    img = make_fake("gemini", MediaType.IMAGE, 4)
    vid = make_fake("runway", MediaType.VIDEO, 2, max_s=10.0)
    monkeypatch.setitem(registry.PROVIDER_CLASSES, "gemini", img)
    monkeypatch.setitem(registry.PROVIDER_CLASSES, "runway", vid)
    return img, vid


@pytest.fixture
def app(make_client, fakes, immich_mock):
    photo_asset(immich_mock, "a1")
    with make_client(GEMINI_API_KEY="k", RUNWAY_API_KEY="k") as c:
        slept = []

        async def sleep(s):
            slept.append(s)

        c.app.state.runner.sleep = sleep
        c.slept = slept
        yield c


def photo_asset(m, id, original=None):
    m.get(f"/api/assets/{id}").mock(return_value=httpx.Response(200, json={
        "id": id, "type": "IMAGE", "fileCreatedAt": "2024-01-01T00:00:00.000Z", "exifInfo": {}}))
    m.get(f"/api/assets/{id}/original").mock(return_value=httpx.Response(200, content=original or jpeg()))
    return m.get(f"/api/assets/{id}/thumbnail").mock(return_value=httpx.Response(200, content=jpeg("green")))


def video_asset(m, id, duration="0:00:03.000000", content=b""):
    m.get(f"/api/assets/{id}").mock(return_value=httpx.Response(200, json={
        "id": id, "type": "VIDEO", "duration": duration, "fileCreatedAt": "2024-01-01T00:00:00.000Z", "exifInfo": {}}))
    m.get(f"/api/assets/{id}/original").mock(return_value=httpx.Response(200, content=content))


def wait(c, id, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{id}").json()
        if j["status"] in ("done", "failed"):
            return j
        time.sleep(0.02)
    raise AssertionError(j)


def submit(c, **body):
    r = c.post("/api/jobs", json={"asset_id": "a1", "custom_prompt": "make it blue", **body})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_photo_job_runs_to_done_and_writes_files(app, fakes, tmp_path):
    id = submit(app, variations=2)
    j = wait(app, id)
    assert j["status"] == "done" and j["provider_id"] == "gemini" and j["provider_model"] == "fake-1"
    req = fakes[0].calls[0]
    assert req.mime == "image/jpeg" and req.prompt.startswith("make it blue") and "recognizable" in req.prompt
    assert [r["index"] for r in j["results"]] == [0, 1]
    r0 = j["results"][0]
    assert r0["mime"] == "image/jpeg" and (r0["width"], r0["height"]) == (32, 24) and r0["discarded"] is False
    f = tmp_path / "results" / id / "0.jpg"
    assert f.is_file() and (tmp_path / "results" / id / "1.jpg").is_file()
    m = app.get(r0["url"], headers={"Range": "bytes=0-9"})
    assert m.status_code == 206 and len(m.content) == 10
    h = app.get("/api/history").json()
    assert h["next_page"] is None and h["items"][0]["id"] == id and len(h["items"][0]["results"]) == 2
    assert app.post(f"/api/results/{r0['id']}/discard").status_code == 200
    assert not f.exists() and app.get(r0["url"]).status_code == 404
    assert app.get(f"/api/jobs/{id}").json()["results"][0]["discarded"] is True


def test_style_job_uses_style_and_history_name(app, fakes):
    id = submit(app, custom_prompt=None, style_id="anime")
    j = wait(app, id)
    assert j["status"] == "done" and j["style_name"] == "Anime"
    assert "anime" in fakes[0].calls[0].prompt and fakes[0].calls[0].negative_prompt


def test_variations_capped_422(app):
    r = app.post("/api/jobs", json={"asset_id": "a1", "custom_prompt": "x", "variations": 5})
    assert r.status_code == 422 and "variation" in r.json()["detail"].lower()


def test_provider_wrong_media_422(app, immich_mock):
    video_asset(immich_mock, "v1")
    r = app.post("/api/jobs", json={"asset_id": "v1", "custom_prompt": "x", "provider_id": "gemini"})
    assert r.status_code == 422 and "video" in r.json()["detail"]
    r = app.post("/api/jobs", json={"asset_id": "a1", "custom_prompt": "x", "provider_id": "nope"})
    assert r.status_code == 422


def test_video_clip_too_long_422(app, immich_mock):
    video_asset(immich_mock, "v1", duration="0:01:00.000000")
    r = app.post("/api/jobs", json={"asset_id": "v1", "custom_prompt": "x", "provider_id": "runway", "clip_start": 0, "clip_end": 20})
    assert r.status_code == 422 and "10" in r.json()["detail"]
    r = app.post("/api/jobs", json={"asset_id": "v1", "custom_prompt": "x", "provider_id": "runway", "clip_start": 5, "clip_end": 5})
    assert r.status_code == 422


def test_video_job_runs_to_done(app, fakes, immich_mock, tmp_path):
    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=24:duration=4",
                    "-f", "lavfi", "-i", "sine=duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    str(src)], check=True)
    video_asset(immich_mock, "v1", duration="0:00:04.000000", content=src.read_bytes())
    id = submit(app, asset_id="v1", provider_id="runway", clip_start=1, clip_end=3)
    j = wait(app, id, timeout=60)
    assert j["status"] == "done", j
    req = fakes[1].calls[0]
    assert req.media_type is MediaType.VIDEO and req.options == {"fps": 24.0, "frames": 48}
    r0 = j["results"][0]
    assert r0["mime"] == "video/mp4" and abs(r0["duration_s"] - 2) < 0.2 and (r0["width"], r0["height"]) == (320, 180)
    assert (tmp_path / "results" / id / "0.mp4").is_file()
    assert not (tmp_path / "tmp" / id).exists()


def test_rate_limit_retried_once_then_fails(app, fakes):
    fake = fakes[0]
    fake.script = [RateLimited("slow down"), RateLimited("slow down")]
    j = wait(app, submit(app))
    assert j["status"] == "failed" and j["error_code"] == "rate_limited" and j["error_message"] == "slow down"
    assert len(fake.calls) == 2 and app.slept == [5]
    fake.script = [RateLimited("once")]
    assert wait(app, submit(app))["status"] == "done"


def test_timeout_maps_to_timeout_code(app, fakes):
    fakes[0].timeout, fakes[0].delay = 0.05, 1.0
    j = wait(app, submit(app))
    assert j["error_code"] == "timeout" and len(fakes[0].calls) == 2


def test_refusal_sets_error_code(app, fakes):
    fakes[0].script = [ContentRefused("no faces please")]
    j = wait(app, submit(app))
    assert (j["status"], j["error_code"], j["error_message"]) == ("failed", "content_refused", "no faces please")
    assert len(fakes[0].calls) == 1 and j["results"] == []


def test_delete_failed_job_only(app, fakes):
    ok = wait(app, submit(app))
    fakes[0].script = [ContentRefused("no")]
    bad = wait(app, submit(app))["id"]
    assert app.delete(f"/api/jobs/{ok['id']}").status_code == 409
    assert app.delete(f"/api/jobs/{bad}").status_code == 200
    assert app.get(f"/api/jobs/{bad}").status_code == 404
    assert [j["id"] for j in app.get("/api/history").json()["items"]] == [ok["id"]]
    assert app.delete(f"/api/jobs/{bad}").status_code == 404


def test_restart_marks_interrupted(make_client, fakes, tmp_path):
    with make_client() as c:
        conn = c.app.state.conn
        for id, st in [("j1", "queued"), ("j2", "running"), ("j3", "done")]:
            conn.execute("insert into jobs(id, source_asset_id, media_type, status) values(?, 'a', 'image', ?)", (id, st))
        conn.commit()
    with make_client() as c:
        rows = {r["id"]: r for r in c.app.state.conn.execute("select * from jobs")}
        assert [rows[i]["status"] for i in ("j1", "j2", "j3")] == ["failed", "failed", "done"]
        assert rows["j1"]["error_code"] == "interrupted" and rows["j2"]["error_message"] == "Interrupted"
        assert rows["j3"]["error_code"] is None


def test_sse_streams_status_changes(app, fakes, monkeypatch):
    monkeypatch.setattr(jobs_api, "PING_S", 0.05)
    fakes[0].delay = 0.4
    id = submit(app, custom_prompt=None, style_id="anime")
    events, pinged = [], False
    with app.stream("GET", f"/api/jobs/{id}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        assert r.headers["cache-control"] == "no-cache" and r.headers["x-accel-buffering"] == "no"
        for line in r.iter_lines():
            pinged |= line == ": ping"
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    assert pinged
    assert events[-1]["status"] == "done" and any(e["status"] == "running" for e in events)
    assert next(e for e in events if e["status"] == "running")["message"] == "Drawing in anime style…"
    # a finished job sends its final state and ends
    with app.stream("GET", f"/api/jobs/{id}/events") as r:
        lines = [l for l in r.iter_lines() if l.startswith("data: ")]
    assert [json.loads(l[6:])["status"] for l in lines] == ["done"]
    assert app.get("/api/jobs/nope/events").status_code == 404


@pytest.mark.parametrize("limit", [1, 2])
def test_concurrency_limits(make_client, fakes, immich_mock, limit):
    photo_asset(immich_mock, "a1")
    fakes[0].delay = 0.15
    with make_client(GEMINI_API_KEY="k", MAX_PHOTO_JOBS=str(limit)) as c:
        ids = [submit(c) for _ in range(4)]
        assert all(wait(c, i)["status"] == "done" for i in ids)
    assert fakes[0].peak == limit


def test_cleanup_deletes_only_old_unsaved_undiscarded(tmp_path):
    conn = connect(tmp_path)
    now = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
    old, new = (now - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S"), (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("insert into jobs(id, source_asset_id, media_type, status, created_at) values('old', 'a', 'image', 'done', ?)", (old,))
    conn.execute("insert into jobs(id, source_asset_id, media_type, status, created_at) values('new', 'a', 'image', 'done', ?)", (new,))
    files = {}
    for rid, job, saved, discarded in [("r1", "old", None, 0), ("r2", "old", "imm1", 0), ("r3", "old", None, 1), ("r4", "new", None, 0)]:
        f = tmp_path / "results" / job / f"{rid}.jpg"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
        files[rid] = f
        conn.execute('insert into results(id, job_id, "index", file_path, saved_asset_id, discarded) values(?, ?, 0, ?, ?, ?)',
                     (rid, job, str(f), saved, discarded))
    conn.commit()
    assert cleanup_results(conn, tmp_path, 14, now) == 1
    assert not files["r1"].exists() and all(files[r].exists() for r in ("r2", "r3", "r4"))
    assert conn.execute("select file_path from results where id='r1'").fetchone()[0] is None


def test_raw_falls_back_to_preview(make_client, fakes, immich_mock):
    preview = photo_asset(immich_mock, "a1", original=b"RAW-not-decodable")
    with make_client(GEMINI_API_KEY="k") as c:
        j = wait(c, submit(c))
    assert j["status"] == "done" and preview.called
    assert Image.open(io.BytesIO(fakes[0].calls[0].data)).getpixel((0, 0))[1] > 100  # green preview was sent


def test_db_touching_handlers_run_on_the_event_loop():
    # sync handlers run in a threadpool and would share the sqlite connection with the runner's loop
    import inspect
    from app.api import jobs, library, settings, styles
    sync = [r.path for m in (jobs, library, settings, styles) for r in m.router.routes if not inspect.iscoroutinefunction(r.endpoint)]
    assert sync == []


def test_history_reads_styles_once_per_request(app, monkeypatch):
    s = app.app.state
    with s.conn:
        for i in range(5):
            s.conn.execute("insert into jobs(id, source_asset_id, media_type, status, style_id) values(?, 'a', 'image', 'done', ?)",
                           (f"j{i}", "anime" if i % 2 else "gone"))
    calls = []
    real = type(s.styles).all
    monkeypatch.setattr(type(s.styles), "all", lambda self: calls.append(1) or real(self))
    items = app.get("/api/history").json()["items"]
    assert len(calls) == 1 and len(items) == 5
    assert {(i["style_id"], i["style_name"]) for i in items} == {("anime", "Anime"), ("gone", None)}
