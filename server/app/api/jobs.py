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
    parent = row["parent_result_id"] and request.app.state.conn.execute(
        "select job_id from results where id = ?", (row["parent_result_id"],)).fetchone()
    # a style deleted since has no name
    return {**dict(row), "style_name": style_names.get(row["style_id"]), "parent_job_id": parent["job_id"] if parent else None,
            "results": [_result(r) for r in results]}


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
    # finished remixes whose every result was discarded (before discard deleted rows) are hidden
    rows = request.app.state.conn.execute(
        "select * from jobs where not (status = 'done' and not exists "
        "(select 1 from results where job_id = jobs.id and discarded = 0)) "
        "order by created_at desc, rowid desc limit ? offset ?",
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


def _versions(conn, result_id: str) -> set[str]:
    """Every result in the same edit tree: what it was edited from, and every edit made from any of those."""
    seen, todo = set(), [result_id]
    while todo:
        rid = todo.pop()
        if rid in seen:
            continue
        seen.add(rid)
        up = conn.execute("select j.parent_result_id from results r join jobs j on j.id = r.job_id where r.id = ?", (rid,)).fetchone()
        if up and up[0]:
            todo.append(up[0])
        todo += [r[0] for r in conn.execute(
            "select r.id from results r join jobs j on j.id = r.job_id where j.parent_result_id = ?", (rid,))]
    return seen


@router.post("/results/{id}/discard")
async def discard_result(id: str, request: Request):
    """Removes the result and all its versions from History; versions already in Immich stay."""
    _result_row(request, id)
    conn = request.app.state.conn
    versions = _versions(conn, id)
    marks = ",".join("?" * len(versions))
    rows = conn.execute(f"select id, job_id, file_path from results where id in ({marks}) and saved_asset_id is null",
                        list(versions)).fetchall()
    for r in rows:
        if r["file_path"]:
            Path(r["file_path"]).unlink(missing_ok=True)
    with conn:
        conn.executemany("delete from results where id = ?", [(r["id"],) for r in rows])
        # jobs left with no results (incl. failed edits of these versions) leave History; running ones finish first
        gone = [j[0] for j in conn.execute(
            f"select id from jobs where (id in ({','.join('?' * len(rows)) or 'null'}) or parent_result_id in ({marks})) "
            "and status in ('done', 'failed') and not exists (select 1 from results where job_id = jobs.id)",
            [r["job_id"] for r in rows] + list(versions))]
        conn.executemany("delete from jobs where id = ?", [(j,) for j in gone])
    for j in gone:
        shutil.rmtree(runner(request).data_dir / "results" / j, ignore_errors=True)
    return {"ok": True, "deleted_jobs": gone}


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
