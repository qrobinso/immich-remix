import json
import shutil
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from ..auth import require_auth
from ..jobs import JobCreate, JobRejected, JobRunner
from ..writeback import STEPS, SaveContext, save_result

router = APIRouter(prefix="/api", dependencies=[Depends(require_auth)])
PING_S = 15.0
PAGE_SIZE = 30


def runner(request: Request) -> JobRunner:
    return request.app.state.runner


def _result(r) -> dict:
    return {"id": r["id"], "index": r["index"], "url": f"/api/results/{r['id']}/media", "mime": r["mime"],
            "width": r["width"], "height": r["height"], "duration_s": r["duration_s"],
            "saved_asset_id": r["saved_asset_id"], "discarded": bool(r["discarded"]),
            "saved": bool(r["saved_at"]), "save_error": r["save_error"],
            "failed_step": STEPS[STEPS.index(r["save_step"]) + 1 if r["save_step"] else 0] if r["save_error"] else None}


def _style_names(request: Request) -> dict[str, str]:
    return {st.id: st.name for st in request.app.state.styles.all()}


def _job(request: Request, row, style_names: dict[str, str]) -> dict:
    results = request.app.state.conn.execute('select * from results where job_id = ? order by "index"', (row["id"],)).fetchall()
    # a style deleted since has no name
    return {**dict(row), "style_name": style_names.get(row["style_id"]), "results": [_result(r) for r in results]}


async def _start(request: Request, coro) -> dict:
    try:
        return {"id": await coro}
    except JobRejected as e:
        raise HTTPException(422, str(e))
    except httpx.HTTPStatusError as e:
        raise HTTPException(404 if e.response.status_code == 404 else 502, "Immich could not serve this asset")
    except httpx.HTTPError:
        raise HTTPException(502, "Cannot reach Immich")


@router.post("/jobs")
async def create_job(req: JobCreate, request: Request):
    return await _start(request, runner(request).submit(req))


@router.post("/jobs/{id}/retry")
async def retry_job(id: str, request: Request):
    _row(request, id)
    return await _start(request, runner(request).retry(id))


def _row(request: Request, id: str):
    row = request.app.state.conn.execute("select * from jobs where id = ?", (id,)).fetchone()
    if row is None:
        raise HTTPException(404, "No such job")
    return row


@router.get("/jobs/{id}")
async def get_job(id: str, request: Request):
    return _job(request, _row(request, id), _style_names(request))


@router.delete("/jobs/{id}")
async def delete_job(id: str, request: Request):
    if _row(request, id)["status"] != "failed":
        raise HTTPException(409, "Only failed remixes can be deleted")
    shutil.rmtree(runner(request).data_dir / "results" / id, ignore_errors=True)
    with request.app.state.conn as conn:
        conn.execute("delete from results where job_id = ?", (id,))
        conn.execute("delete from jobs where id = ?", (id,))
    return {"ok": True}


@router.get("/jobs/{id}/events")
async def job_events(id: str, request: Request):
    _row(request, id)

    async def stream():
        async for ev in runner(request).events(id, keepalive=PING_S):
            yield ": ping\n\n" if ev is None else f"data: {json.dumps(ev)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/history")
async def history(request: Request, page: int = 1):
    page = max(page, 1)
    rows = request.app.state.conn.execute("select * from jobs order by created_at desc, rowid desc limit ? offset ?",
                                          (PAGE_SIZE + 1, (page - 1) * PAGE_SIZE)).fetchall()
    names = _style_names(request)
    return {"items": [_job(request, r, names) for r in rows[:PAGE_SIZE]], "next_page": page + 1 if len(rows) > PAGE_SIZE else None}


def _result_row(request: Request, id: str):
    r = request.app.state.conn.execute("select * from results where id = ?", (id,)).fetchone()
    if r is None:
        raise HTTPException(404, "No such result")
    return r


@router.get("/results/{id}/media")
async def result_media(id: str, request: Request):
    r = _result_row(request, id)
    if r["discarded"] or not r["file_path"] or not Path(r["file_path"]).is_file():
        raise HTTPException(404, "This result is no longer cached")
    return FileResponse(r["file_path"], media_type=r["mime"])


@router.post("/results/{id}/discard")
async def discard_result(id: str, request: Request):
    r = _result_row(request, id)
    if r["file_path"]:
        Path(r["file_path"]).unlink(missing_ok=True)
    with request.app.state.conn:
        request.app.state.conn.execute("update results set discarded = 1 where id = ?", (id,))
    return {"ok": True}


@router.post("/results/{id}/save")
async def save(id: str, request: Request):
    r = _result_row(request, id)
    if r["discarded"]:
        raise HTTPException(409, "This result was discarded")
    s = request.app.state
    ctx = SaveContext(s.conn, s.settings, s.immich, s.styles, s.providers, Path(s.settings.env.DATA_DIR),
                      s.settings.env.IMMICH_PUBLIC_URL or s.settings.env.IMMICH_URL)
    o = await save_result(id, ctx)
    if o.failed_step is None:
        return {"asset_id": o.asset_id, "link": o.link}
    # an upload failure leaves no asset: plain 502; later steps keep the asset and answer 207
    body = {"asset_id": o.asset_id, "failed_step": o.failed_step, "error": o.error}
    return JSONResponse(body, status_code=207 if o.asset_id else 502)
