import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .config import Env
from .db import Settings, connect

STATIC = Path(__file__).parent / "static"


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    app = FastAPI(title="immich-remix")
    raw = {k: v for k, v in dict(os.environ if env is None else env).items() if v != ""}  # empty = unset
    app.state.env = Env.model_validate(raw)
    data_dir = Path(app.state.env.DATA_DIR)
    app.state.conn = connect(data_dir)
    app.state.settings = Settings(app.state.conn, app.state.env, data_dir)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    if (STATIC / "index.html").exists():

        @app.get("/{path:path}")
        def spa(path: str):
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404)
            f = (STATIC / path).resolve()
            return FileResponse(f if f.is_file() and f.is_relative_to(STATIC) else STATIC / "index.html")

    return app
