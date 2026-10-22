import asyncio
import io
import logging
import shutil
import sqlite3
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from .db import Settings
from .immich import Immich
from .media.image import UnsupportedImage, mark_spot, prepare_image, source_meta
from .media.video import MediaError, finalize_video, prepare_video, probe
from .providers.base import MediaType, ProviderFailure, RateLimited, RemixRequest, Timeout
from .providers.registry import Registry
from .styles import Style, StyleLibrary, build_edit_prompt, build_prompt

log = logging.getLogger(__name__)
MEDIA_CAP = {MediaType.IMAGE: 4, MediaType.VIDEO: 2}
NOUN = {MediaType.IMAGE: "photos", MediaType.VIDEO: "videos"}
TERMINAL = ("done", "failed")
RETRY_DELAY_S = 5
CLEANUP_EVERY_S = 24 * 3600


class JobCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an unknown field is a client/server mismatch, not something to drop

    asset_id: str
    style_id: str | None = None
    custom_prompt: str | None = None
    provider_id: str | None = None  # None: the style's default, then the settings default
    variations: int = Field(1, ge=1)
    clip_start: float | None = None
    clip_end: float | None = None
    parent_result_id: str | None = None  # an edit of this earlier result; custom_prompt holds the edit
    edit_x: float | None = Field(None, ge=0, le=1)  # optional spot the edit is about, as fractions of width/height
    edit_y: float | None = Field(None, ge=0, le=1)


class JobRejected(Exception):
    """The request can't run as asked; the message is shown to the user (422)."""


def parse_duration(s: str | None) -> float:
    h, m, sec = (s or "").split(":")  # Immich: "H:MM:SS.ffffff"
    return int(h) * 3600 + int(m) * 60 + float(sec)


def _ts(dt: datetime) -> str:  # sqlite datetime('now') format, UTC
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def cleanup_results(conn: sqlite3.Connection, data_dir: Path, days: int, now: datetime) -> int:
    """Deletes cached files of old results that were neither saved nor discarded; rows stay for history."""
    rows = conn.execute(
        "select r.id, r.file_path from results r join jobs j on j.id = r.job_id where j.created_at < ? "
        "and r.saved_asset_id is null and r.discarded = 0 and r.file_path is not null",
        (_ts(now - timedelta(days=days)),)).fetchall()
    for r in rows:
        p = Path(r["file_path"])
        p.unlink(missing_ok=True)
        try:
            p.parent.rmdir()  # only once the job dir is empty
        except OSError:
            pass
        conn.execute("update results set file_path = null where id = ?", (r["id"],))
    conn.commit()
    return len(rows)


def _to_jpeg(data: bytes, quality: int) -> tuple[bytes, int, int]:
    im = Image.open(io.BytesIO(data)).convert("RGB")
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality)
    return out.getvalue(), im.width, im.height


class JobRunner:
    def __init__(self, conn: sqlite3.Connection, settings: Settings, registry: Registry, immich: Immich,
                 styles: StyleLibrary, data_dir: Path):
        self.conn, self.settings, self.registry, self.immich, self.styles = conn, settings, registry, immich, styles
        self.data_dir = Path(data_dir)
        self.sleep = asyncio.sleep  # tests replace it
        self.sems = {MediaType.IMAGE: asyncio.Semaphore(settings.env.MAX_PHOTO_JOBS),
                     MediaType.VIDEO: asyncio.Semaphore(settings.env.MAX_VIDEO_JOBS)}
        self.tasks: set[asyncio.Task] = set()
        self.state: dict[str, dict] = {}  # live event of non-terminal jobs
        self.subs: dict[str, set[asyncio.Queue]] = {}

    # lifecycle

    def start(self) -> None:
        with self.conn:
            self.conn.execute("update jobs set status='failed', error_code='interrupted', error_message='Interrupted', "
                              "finished_at=datetime('now') where status in ('queued', 'running')")
        shutil.rmtree(self.data_dir / "tmp", ignore_errors=True)  # leftovers of interrupted video jobs
        self._spawn(self._cleanup_loop())

    async def shutdown(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)

    async def _cleanup_loop(self) -> None:
        while True:
            try:
                n = cleanup_results(self.conn, self.data_dir, int(self.settings.get("cleanup.days")), datetime.now(timezone.utc))
                if n:
                    log.info("cleanup removed %d cached results", n)
            except Exception:
                log.exception("cleanup failed")
            await asyncio.sleep(CLEANUP_EVERY_S)

    # submit

    def _resolve(self, req: JobCreate, media: MediaType, style: Style | None):
        pid = req.provider_id or (style and style.default_provider.get(media)) or self.settings.get(f"default_provider.{media.value}")
        if not pid:
            raise JobRejected(f"No provider is set up for {NOUN[media]}")
        if pid not in {p.id for p in self.registry.for_media(media)}:
            raise JobRejected(f"{pid} can't remix {NOUN[media]} or isn't set up and healthy")
        return self.registry.get(pid)

    async def _edit_parent(self, req: JobCreate) -> tuple[sqlite3.Row, bytes]:
        if not req.custom_prompt or not req.custom_prompt.strip():
            raise JobRejected("Describe the change you want")
        r = self.conn.execute("select r.*, j.source_asset_id, j.style_id, j.provider_id from results r "
                              "join jobs j on j.id = r.job_id where r.id = ?", (req.parent_result_id,)).fetchone()
        if r is None or r["discarded"] or r["mime"] != "image/jpeg":
            raise JobRejected("That remix can't be edited")
        f = Path(r["file_path"])
        if f.is_file():
            return r, f.read_bytes()
        if r["saved_asset_id"]:  # saved results live in Immich only
            return r, await self.immich.original(r["saved_asset_id"])
        raise JobRejected("That remix is no longer available")

    async def submit(self, req: JobCreate) -> str:
        parent = edit_input = None
        if req.parent_result_id:
            parent, edit_input = await self._edit_parent(req)
            req = req.model_copy(update={"asset_id": parent["source_asset_id"], "style_id": parent["style_id"],
                                         "provider_id": req.provider_id or parent["provider_id"]})
        style = None
        if req.style_id:
            try:
                style = self.styles.get(req.style_id)
            except KeyError:
                raise JobRejected(f"Unknown style {req.style_id}")
        try:
            prompt, negative = ((build_edit_prompt(req.custom_prompt, req.edit_x is not None), None) if parent
                                else build_prompt(style, req.custom_prompt))
        except ValueError as e:
            raise JobRejected(str(e))
        asset = await self.immich.asset(req.asset_id)
        media = MediaType.VIDEO if asset.get("type") == "VIDEO" else MediaType.IMAGE
        if style and media not in style.media_types:
            raise JobRejected(f"{style.name} doesn't support {NOUN[media]}")
        provider = self._resolve(req, media, style)
        cap = min(MEDIA_CAP[media], provider.max_variations.get(media, 1))
        if req.variations > cap:
            raise JobRejected(f"{provider.name} allows at most {cap} variation{'s' if cap > 1 else ''} for {NOUN[media]}")
        start = end = None
        if media is MediaType.VIDEO:
            try:
                duration = parse_duration(asset.get("duration"))
            except (ValueError, AttributeError):
                raise JobRejected("Unknown video duration")
            limit = provider.max_video_seconds
            start = req.clip_start if req.clip_start is not None else 0.0
            end = req.clip_end if req.clip_end is not None else min(duration, start + limit if limit else duration)
            if start < 0 or end <= start:
                raise JobRejected("The clip must end after it starts")
            if limit and end - start > limit + 1e-6:
                raise JobRejected(f"{provider.name} takes clips of at most {limit:g} s")
        id = uuid.uuid4().hex
        with self.conn:
            self.conn.execute(
                "insert into jobs(id, source_asset_id, media_type, style_id, custom_prompt, provider_id, variations, "
                "clip_start_s, clip_end_s, parent_result_id, edit_x, edit_y) values(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (id, req.asset_id, media.value, req.style_id, req.custom_prompt, provider.id, req.variations, start, end,
                 req.parent_result_id, req.edit_x, req.edit_y))
        ev = {"status": "queued", "message": "Applying your edit…" if parent else (style and style.status_text) or "Remixing…"}
        if media is MediaType.VIDEO:
            ev["eta_s"] = provider.typical_seconds
        self._emit(id, ev)
        edit = (edit_input, req.edit_x, req.edit_y) if parent else None
        self._spawn(self._run(id, asset, media, style, provider, prompt, negative, req.variations, start, end, edit))
        return id

    async def retry(self, job_id: str) -> str:
        r = self._row(job_id)
        return await self.submit(JobCreate(asset_id=r["source_asset_id"], style_id=r["style_id"], custom_prompt=r["custom_prompt"],
                                           provider_id=r["provider_id"], variations=r["variations"],
                                           clip_start=r["clip_start_s"], clip_end=r["clip_end_s"],
                                           parent_result_id=r["parent_result_id"], edit_x=r["edit_x"], edit_y=r["edit_y"]))

    # events

    def _row(self, job_id: str) -> sqlite3.Row:
        r = self.conn.execute("select * from jobs where id = ?", (job_id,)).fetchone()
        if r is None:
            raise KeyError(job_id)
        return r

    def _emit(self, job_id: str, ev: dict) -> None:
        if ev["status"] in TERMINAL:
            self.state.pop(job_id, None)
        else:
            self.state[job_id] = ev
        for q in self.subs.get(job_id, ()):
            q.put_nowait(ev)

    def _status(self, job_id: str, status: str, **ev) -> None:
        self._emit(job_id, {**self.state.get(job_id, {}), "status": status, **ev})

    async def events(self, job_id: str, keepalive: float | None = None) -> AsyncIterator[dict | None]:
        """Current state first, then each change until a terminal state; yields None after `keepalive` idle seconds."""
        if job_id in self.state:
            ev = self.state[job_id]
        else:
            r = self._row(job_id)
            ev = {"status": r["status"], "message": r["error_message"] if r["status"] == "failed" else "Done"}
            if r["status"] == "failed":
                ev["error_code"] = r["error_code"]
        q: asyncio.Queue = asyncio.Queue()
        self.subs.setdefault(job_id, set()).add(q)
        try:
            while True:
                yield ev
                if ev["status"] in TERMINAL:
                    return
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), keepalive)
                        break
                    except TimeoutError:
                        yield None
        finally:
            self.subs[job_id].discard(q)
            if not self.subs[job_id]:
                del self.subs[job_id]

    # run

    async def _remix(self, provider, req: RemixRequest):
        for attempt in range(2):
            try:
                try:
                    async with asyncio.timeout(provider.timeout):
                        return await provider.remix(req)
                except TimeoutError:
                    raise Timeout(f"No answer after {provider.timeout:g} s") from None
            except (RateLimited, Timeout):
                if attempt:
                    raise
                await self.sleep(RETRY_DELAY_S)

    def _style_reference(self, opts: dict) -> bytes | None:
        name = opts.get("style_image")
        if not name:
            return None
        for d in (self.styles.user_dir, self.styles.builtin_dir):
            f = d / Path(name).name  # file name only: never read outside the style dirs
            if f.is_file():
                return f.read_bytes()
        return None

    async def _photo_input(self, asset_id: str, max_px: int) -> bytes:
        prep = lambda b: asyncio.to_thread(prepare_image, b, max_px)
        if self.settings.get("photo.source") == "preview":
            return await prep(await self.immich.preview(asset_id))
        try:
            return await prep(await self.immich.original(asset_id))
        except UnsupportedImage:  # RAW and other formats Pillow can't read
            return await prep(await self.immich.preview(asset_id))

    async def _download(self, asset_id: str, dest: Path) -> None:
        up = await self.immich.stream(f"/assets/{asset_id}/original", {})
        try:
            up.raise_for_status()
            with dest.open("wb") as f:
                async for chunk in up.aiter_bytes():
                    f.write(chunk)
        finally:
            await up.aclose()

    async def _run(self, id, asset, media, style, provider, prompt, negative, variations, start, end, edit=None) -> None:
        tmp = self.data_dir / "tmp" / id
        out_dir = self.data_dir / "results" / id
        try:
            async with self.sems[media]:
                with self.conn:
                    self.conn.execute("update jobs set status='running' where id=?", (id,))
                self._status(id, "running")
                opts = dict(style.providers.get(provider.id, {})) if style and not edit else {}
                if media is MediaType.IMAGE:
                    max_px = min(int(self.settings.get("photo.max_px")), provider.max_input_px)
                    if edit:
                        data = await asyncio.to_thread(prepare_image, edit[0], max_px)
                        if edit[1] is not None and edit[2] is not None:
                            data = await asyncio.to_thread(mark_spot, data, edit[1], edit[2])
                    else:
                        data = await self._photo_input(asset["id"], max_px)
                    mime = "image/jpeg"
                else:
                    tmp.mkdir(parents=True, exist_ok=True)
                    original, clip = tmp / "original", tmp / "input.mp4"
                    await self._download(asset["id"], original)
                    info = await prepare_video(original, clip, start, end, int(self.settings.get("video.max_height")))
                    data, mime = clip.read_bytes(), "video/mp4"
                    opts |= {"fps": info.fps, "frames": round(info.duration * info.fps)}
                res = await self._remix(provider, RemixRequest(
                    media_type=media, data=data, mime=mime, prompt=prompt, negative_prompt=negative,
                    strength=style.strength if style and not edit else None, variations=variations, seed=None,
                    style_reference=self._style_reference(opts), options=opts))
                out_dir.mkdir(parents=True, exist_ok=True)
                rows = []
                for i, out in enumerate(res.outputs):
                    if media is MediaType.IMAGE:
                        f = out_dir / f"{i}.jpg"
                        jpg, w, h = await asyncio.to_thread(_to_jpeg, out, int(self.settings.get("photo.jpeg_quality")))
                        f.write_bytes(jpg)
                        rows.append((i, f, "image/jpeg", w, h, None))
                    else:
                        raw, f = tmp / f"remix{i}.mp4", out_dir / f"{i}.mp4"
                        raw.write_bytes(out)
                        await finalize_video(raw, original, f, start, end, bool(self.settings.get("video.keep_audio")),
                                             source_meta(asset))
                        vi = await probe(f)
                        rows.append((i, f, "video/mp4", vi.width, vi.height, vi.duration))
                with self.conn:
                    self.conn.executemany(
                        'insert into results(id, job_id, "index", file_path, mime, width, height, duration_s) values(?, ?, ?, ?, ?, ?, ?, ?)',
                        [(uuid.uuid4().hex, id, i, str(f), m, w, h, d) for i, f, m, w, h, d in rows])
                    self.conn.execute("update jobs set status='done', provider_model=?, cost_estimate_usd=?, "
                                      "finished_at=datetime('now') where id=?", (res.provider_model, res.cost_estimate_usd, id))
                self._status(id, "done", message="Done")
        except asyncio.CancelledError:
            raise  # shutdown: start() marks it interrupted next time
        except Exception as e:
            if isinstance(e, ProviderFailure):
                code, msg = e.code, str(e)
            elif isinstance(e, (MediaError, UnsupportedImage)):
                code, msg = "media_error", str(e).strip()[-500:] or "Could not process this media"
                log.warning("job %s media error: %s", id, msg)
            else:
                code, msg = "internal", "Something went wrong"
                log.exception("job %s failed", id)
            shutil.rmtree(out_dir, ignore_errors=True)
            with self.conn:
                self.conn.execute("update jobs set status='failed', error_code=?, error_message=?, finished_at=datetime('now') "
                                  "where id=?", (code, msg, id))
            self._status(id, "failed", message=msg, error_code=code)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
