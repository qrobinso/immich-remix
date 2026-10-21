import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .db import Settings
from .immich import Immich
from .media.image import encode_output, source_meta
from .providers.registry import Registry
from .styles import StyleLibrary

STEPS = ("upload", "metadata", "stack", "album", "tag")
_locks: dict[str, asyncio.Lock] = {}  # shortcut: one lock per result id kept for the process lifetime; fine at this scale


@dataclass
class SaveContext:
    conn: sqlite3.Connection
    settings: Settings
    immich: Immich
    styles: StyleLibrary
    providers: Registry
    data_dir: Path
    public_url: str


@dataclass
class SaveOutcome:
    asset_id: str | None = None
    link: str | None = None
    failed_step: str | None = None
    error: str | None = None


def describe(ctx: SaveContext, job) -> str:
    sid = job["style_id"]
    try:
        style = ctx.styles.get(sid).name if sid else "Custom"
    except KeyError:
        style = sid
    try:
        backend = ctx.providers.get(job["provider_id"]).name
    except KeyError:
        backend = job["provider_id"]
    d = f"Remix: {style} · {backend}"
    return f"{d} · {job['custom_prompt']}" if job["custom_prompt"] else d


async def save_result(result_id: str, ctx: SaveContext) -> SaveOutcome:
    lock = _locks.setdefault(result_id, asyncio.Lock())
    async with lock:
        return await _save(result_id, ctx)


async def _save(result_id: str, ctx: SaveContext) -> SaveOutcome:
    conn = ctx.conn
    r = conn.execute("select * from results where id = ?", (result_id,)).fetchone()
    link = lambda a: f"{ctx.public_url.rstrip('/')}/photos/{a}"
    if r["saved_at"]:
        return SaveOutcome(r["saved_asset_id"], link(r["saved_asset_id"]))
    job = conn.execute("select * from jobs where id = ?", (r["job_id"],)).fetchone()
    new = r["saved_asset_id"]  # set right after upload, so a retry never uploads again
    done = STEPS.index(r["save_step"]) + 1 if r["save_step"] else 0
    im, st = ctx.immich, ctx.settings
    step = STEPS[done] if done < len(STEPS) else "upload"
    try:
        src_id = job["source_asset_id"]
        src = await im.asset(src_id)
        exif = src.get("exifInfo") or {}
        meta = source_meta(src)
        for step in STEPS[done:]:
            if step == "upload":
                f = Path(r["file_path"] or "")
                if not f.is_file():
                    raise FileNotFoundError("The cached result is gone")
                data = await asyncio.to_thread(f.read_bytes)
                if r["mime"] == "image/jpeg":
                    data = await asyncio.to_thread(encode_output, data, meta, describe(ctx, job), int(st.get("photo.jpeg_quality")))
                when = meta.taken_at or datetime.now(timezone.utc)
                new = await im.upload(data, f"remix-{result_id}{f.suffix}", f"immich-remix-{result_id}", when.astimezone(timezone.utc))
                with conn:
                    conn.execute("update results set saved_asset_id = ? where id = ?", (new, result_id))
            elif step == "metadata":
                fields = {"description": describe(ctx, job)}
                if meta.taken_at:
                    fields["dateTimeOriginal"] = meta.taken_at.isoformat()
                if meta.lat is not None and meta.lon is not None:
                    fields |= {"latitude": meta.lat, "longitude": meta.lon}
                if exif.get("timeZone"):
                    fields["timeZone"] = exif["timeZone"]
                await im.update_assets([new], **fields)
            elif step == "stack":
                base = (src.get("stack") or {}).get("primaryAssetId") or src_id
                ids = [base, new] if st.get("save.stack_primary") == "original" else [new, base]
                await im.create_stack(ids)
            elif step == "album" and st.get("save.album"):
                await im.add_to_album(await im.find_or_create_album(st.get("save.album")), [new])
            elif step == "tag" and st.get("save.tag"):
                await im.tag_assets(await im.find_or_create_tag(st.get("save.tag")), [new])
            with conn:
                conn.execute("update results set save_step = ?, save_error = null where id = ?", (step, result_id))
    except Exception as e:
        msg = str(e) or type(e).__name__
        with conn:
            conn.execute("update results set save_error = ? where id = ?", (msg, result_id))
        return SaveOutcome(new, link(new) if new else None, step, msg)
    with conn:
        conn.execute("update results set saved_at = datetime('now') where id = ?", (result_id,))
    if r["file_path"]:
        Path(r["file_path"]).unlink(missing_ok=True)
    return SaveOutcome(new, link(new))
