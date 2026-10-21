import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import piexif
from PIL import Image

from app.config import Env
from app.db import Settings, connect
from app.writeback import SaveContext, save_result

SRC = {"id": "src", "fileCreatedAt": "2024-01-01T00:00:00.000Z", "stack": None,
       "exifInfo": {"dateTimeOriginal": "2020-06-01T12:00:00+02:00", "timeZone": "UTC+2", "latitude": 48.8, "longitude": 2.3}}


def jpg():
    out = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(out, "JPEG")
    return out.getvalue()


def make(tmp_path, src=SRC, **settings):
    conn = connect(tmp_path)
    st = Settings(conn, Env.model_validate({"IMMICH_URL": "http://i", "IMMICH_API_KEY": "k", "DATA_DIR": str(tmp_path)}), tmp_path)
    for k, v in settings.items():
        st.set(k.replace("__", "."), v)
    f = tmp_path / "0.jpg"
    f.write_bytes(jpg())
    conn.execute("insert into jobs(id, source_asset_id, media_type, style_id, custom_prompt, provider_id, status) "
                 "values('j', 'src', 'image', 'wc', 'more blue', 'gemini', 'done')")
    conn.execute("insert into results(id, job_id, \"index\", file_path, mime) values('r', 'j', 0, ?, 'image/jpeg')", (str(f),))
    conn.commit()
    im = MagicMock()
    im.asset = AsyncMock(return_value=src)
    im.upload = AsyncMock(return_value="new")
    for n in ("update_assets", "create_stack", "add_to_album", "tag_assets"):
        setattr(im, n, AsyncMock())
    im.find_or_create_album = AsyncMock(return_value="alb")
    im.find_or_create_tag = AsyncMock(return_value="tag")
    ctx = SaveContext(conn, st, im, SimpleNamespace(get=lambda i: SimpleNamespace(name="Watercolor")),
                      SimpleNamespace(get=lambda i: SimpleNamespace(name="Google Gemini")), tmp_path, "http://pub/")
    return ctx, im, f


async def test_full_sequence_order_and_payloads(tmp_path):
    ctx, im, f = make(tmp_path, save__tag="t")
    o = await save_result("r", ctx)
    assert (o.asset_id, o.link, o.failed_step) == ("new", "http://pub/photos/new", None)
    data, name, dev, when = im.upload.await_args.args
    assert dev == "immich-remix-r" and when.isoformat() == "2020-06-01T10:00:00+00:00"
    exif = piexif.load(data)
    assert exif["0th"][piexif.ImageIFD.Software] == b"immich-remix"
    desc = "Remix: Watercolor · Google Gemini · more blue"
    assert exif["0th"][piexif.ImageIFD.ImageDescription].decode() == desc
    im.update_assets.assert_awaited_once_with(["new"], description=desc, dateTimeOriginal="2020-06-01T12:00:00+02:00",
                                              latitude=48.8, longitude=2.3, timeZone="UTC+2")
    im.create_stack.assert_awaited_once_with(["src", "new"])
    im.add_to_album.assert_awaited_once_with("alb", ["new"])
    im.tag_assets.assert_awaited_once_with("tag", ["new"])
    row = ctx.conn.execute("select * from results").fetchone()
    assert row["saved_asset_id"] == "new" and row["saved_at"] and row["save_step"] == "tag" and not f.exists()


async def test_no_gps_no_date_still_saves(tmp_path):
    ctx, im, _ = make(tmp_path, src={"id": "src", "exifInfo": {}, "fileCreatedAt": "2024-01-01T00:00:00.000Z"})
    o = await save_result("r", ctx)
    assert o.failed_step is None
    assert im.update_assets.await_args.kwargs == {"description": "Remix: Watercolor · Google Gemini · more blue",
                                                  "dateTimeOriginal": "2024-01-01T00:00:00+00:00"}
    assert im.upload.await_args.args[3].year == 2024


async def test_double_save_uploads_once(tmp_path):
    ctx, im, _ = make(tmp_path)
    a, b = await asyncio.gather(save_result("r", ctx), save_result("r", ctx))
    assert a == b and im.upload.await_count == 1 and im.create_stack.await_count == 1


async def test_album_failure_then_retry_resumes_at_album(tmp_path):
    ctx, im, f = make(tmp_path)
    im.add_to_album.side_effect = [RuntimeError("boom"), None]
    o = await save_result("r", ctx)
    assert (o.asset_id, o.failed_step, o.error) == ("new", "album", "boom") and f.exists()
    assert tuple(ctx.conn.execute("select save_step, saved_at from results").fetchone()) == ("stack", None)
    o = await save_result("r", ctx)
    assert o.failed_step is None and o.link == "http://pub/photos/new"
    assert im.upload.await_count == 1 and im.update_assets.await_count == 1 and im.create_stack.await_count == 1
    assert im.add_to_album.await_count == 2 and not f.exists()


async def test_source_in_stack_keeps_existing_primary(tmp_path):
    ctx, im, _ = make(tmp_path, src={**SRC, "stack": {"id": "s", "primaryAssetId": "prim", "assetCount": 2}})
    await save_result("r", ctx)
    im.create_stack.assert_awaited_once_with(["prim", "new"])


async def test_remix_primary_setting(tmp_path):
    ctx, im, _ = make(tmp_path, save__stack_primary="remix")
    await save_result("r", ctx)
    im.create_stack.assert_awaited_once_with(["new", "src"])


async def test_original_never_updated(tmp_path):
    ctx, im, _ = make(tmp_path, save__tag="t")
    await save_result("r", ctx)
    for m in (im.update_assets, im.add_to_album, im.tag_assets):
        assert all("src" not in c.args[-1] for c in m.await_args_list)


def test_route_discarded_409_and_saved_200(client):
    s = client.app.state
    s.conn.execute("insert into jobs(id, source_asset_id, media_type, provider_id, status) values('j', 'src', 'image', 'gemini', 'done')")
    s.conn.execute("insert into results(id, job_id, \"index\", discarded) values('d', 'j', 0, 1)")
    s.conn.execute("insert into results(id, job_id, \"index\", saved_asset_id, saved_at) values('s', 'j', 1, 'x', 'now')")
    s.conn.commit()
    assert client.post("/api/results/d/save").status_code == 409
    r = client.post("/api/results/s/save")
    assert r.status_code == 200 and r.json() == {"asset_id": "x", "link": "http://immich.test/photos/x"}
    assert client.post("/api/results/nope/save").status_code == 404
