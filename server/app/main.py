import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

from .config import Env

STATIC = Path(__file__).parent / "static"


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    app = FastAPI(title="immich-remix")
    app.state.env = Env.model_validate(dict(os.environ if env is None else env))

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
