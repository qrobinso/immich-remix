import asyncio
import io
import os
from datetime import datetime, timezone

import httpx
import piexif
import pytest
from PIL import Image, ImageOps

from app.config import Env
from app.db import Settings, connect
from app.immich import Immich
from app.providers.registry import Registry
from app.styles import BUILTIN_DIR, StyleLibrary
from app.writeback import SaveContext, save_result

pytestmark = pytest.mark.live
ALBUM = "Remixes-test"


def synthetic() -> bytes:
    """Random pixels so the checksum is new; EXIF date 2020-06-01T12:00+02:00 at the Eiffel tower."""
    im = Image.frombytes("RGB", (800, 600), os.urandom(800 * 600 * 3))
    dms = lambda v: ((int(v), 1), (int(v % 1 * 60), 1), (int(round(v * 3600 % 60 * 10000)), 10000))
    exif = {"Exif": {piexif.ExifIFD.DateTimeOriginal: b"2020:06:01 12:00:00", piexif.ExifIFD.OffsetTimeOriginal: b"+02:00"},
            "GPS": {piexif.GPSIFD.GPSLatitudeRef: b"N", piexif.GPSIFD.GPSLatitude: dms(48.8584),
                    piexif.GPSIFD.GPSLongitudeRef: b"E", piexif.GPSIFD.GPSLongitude: dms(2.2945)}}
    out = io.BytesIO()
    im.save(out, "JPEG", quality=90, exif=piexif.dump(exif))
    return out.getvalue()


async def until(fn, what, tries=40):
    for _ in range(tries):
        if (v := await fn()):
            return v
        await asyncio.sleep(1.5)
    raise AssertionError(f"timed out waiting for {what}")


def snap(a: dict) -> dict:
    e = a.get("exifInfo") or {}
    return {"checksum": a["checksum"], "date": e.get("dateTimeOriginal"), "lat": e.get("latitude"), "lon": e.get("longitude")}


async def test_save_roundtrip(live_env, tmp_path):
    im = Immich(live_env["IMMICH_URL"], live_env["IMMICH_API_KEY"])
    http = httpx.AsyncClient()
    try:
        orig_id = await im.upload(synthetic(), "remix-test-original.jpg", "x", datetime(2020, 6, 1, 10, 0, tzinfo=timezone.utc))

        async def extracted():
            a = await im.asset(orig_id)
            return a if (a.get("exifInfo") or {}).get("latitude") is not None and a["exifInfo"].get("dateTimeOriginal") else None

        print(f"\nuploaded original {orig_id} (remix-test-original.jpg)")
        orig = await until(extracted, "EXIF extraction of the original")
        before = snap(orig)
        assert before["date"].startswith("2020-06-01T10:00:00")  # 12:00+02:00 in UTC

        # local stand-in for the Gemini remix (R9: no Gemini quota)
        data = await im.original(orig_id)
        remix = ImageOps.posterize(ImageOps.grayscale(Image.open(io.BytesIO(data))).convert("RGB"), 2)
        f = tmp_path / "results" / "j1" / "0.jpg"
        f.parent.mkdir(parents=True)
        remix.save(f, "JPEG", quality=92)

        conn = connect(tmp_path)
        env = Env.model_validate({"IMMICH_URL": live_env["IMMICH_URL"], "IMMICH_API_KEY": live_env["IMMICH_API_KEY"], "DATA_DIR": str(tmp_path)})
        settings = Settings(conn, env, tmp_path)
        settings.set("save.album", ALBUM)
        styles = StyleLibrary(BUILTIN_DIR, tmp_path / "styles", conn)
        conn.execute("insert into jobs(id, source_asset_id, media_type, style_id, provider_id, status) values('j1', ?, 'image', ?, 'gemini', 'done')",
                     (orig_id, styles.all()[0].id))
        conn.execute("insert into results(id, job_id, \"index\", file_path, mime, width, height) values('r1', 'j1', 0, ?, 'image/jpeg', 800, 600)", (str(f),))
        conn.commit()
        ctx = SaveContext(conn, settings, im, styles, Registry(settings, http), tmp_path, live_env["IMMICH_URL"])

        out = await save_result("r1", ctx)
        assert out.failed_step is None, out
        new_id = out.asset_id
        assert new_id and new_id != orig_id and out.link.endswith(f"/photos/{new_id}")

        async def settled():
            a = await im.asset(new_id)
            e = a.get("exifInfo") or {}
            return a if e.get("latitude") is not None and e.get("dateTimeOriginal") else None

        new = await until(settled, "metadata on the new asset")
        e = new["exifInfo"]
        assert e["dateTimeOriginal"] == before["date"]
        assert abs(e["latitude"] - before["lat"]) < 1e-3 and abs(e["longitude"] - before["lon"]) < 1e-3
        assert e["description"].startswith("Remix: ") and "Google Gemini" in e["description"]

        stack = new["stack"]
        assert stack and stack["primaryAssetId"] == orig_id and stack["assetCount"] == 2
        assert (await im.asset(orig_id))["stack"]["primaryAssetId"] == orig_id

        albums = [a for a in await im._json("GET", "/albums") if a["albumName"] == ALBUM]
        assert len(albums) == 1
        found = await im._json("POST", "/search/metadata", json={"albumIds": [albums[0]["id"]]})
        assert new_id in {a["id"] for a in found["assets"]["items"]}

        assert snap(await im.asset(orig_id)) == before  # the original was never touched
        again = await save_result("r1", ctx)  # a second save must not upload again
        assert again.asset_id == new_id
        print(f'\nTrash the assets in album "{ALBUM}" when done.\noriginal={orig_id} remix={new_id}')
    finally:
        await http.aclose()
        await im.aclose()
