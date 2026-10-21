import os
from contextlib import asynccontextmanager
from collections.abc import Mapping
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse

from .api import auth as auth_api
from .api import jobs as jobs_api, library, settings as settings_api, styles as styles_api
from .auth import Auth
from .config import Env
from .db import Settings, connect
from .immich import Immich
from .jobs import JobRunner
from .providers.registry import Registry
from .styles import BUILTIN_DIR, StyleLibrary

STATIC = Path(__file__).parent / "static"


def create_app(env: Mapping[str, str] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.immich = Immich(app.state.env.IMMICH_URL, app.state.env.IMMICH_API_KEY)
        await library.check_immich(app)  # failure only sets immich_error; History still works
        http = httpx.AsyncClient()
        app.state.providers = Registry(app.state.settings, http)
        await app.state.providers.refresh_health()
        s = app.state
        s.runner = JobRunner(s.conn, s.settings, s.providers, s.immich, s.styles, data_dir)
        s.runner.start()
        yield
        await s.runner.shutdown()
        await http.aclose()
        await app.state.immich.aclose()

    app = FastAPI(title="immich-remix", lifespan=lifespan)
    raw = {k: v for k, v in dict(os.environ if env is None else env).items() if v != ""}  # empty = unset
    app.state.env = Env.model_validate(raw)
    data_dir = Path(app.state.env.DATA_DIR)
    app.state.conn = connect(data_dir)
    app.state.settings = Settings(app.state.conn, app.state.env, data_dir)

    app.state.styles = StyleLibrary(BUILTIN_DIR, data_dir / "styles", app.state.conn)
    app.state.auth = Auth(app.state.env.APP_PASSWORD, data_dir)
    app.include_router(auth_api.router)
    app.include_router(library.router)
    app.include_router(styles_api.router)
    app.include_router(jobs_api.router)
    app.include_router(settings_api.router)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    # SPA fallback as a 404 handler, not a catch-all route, so routes added after create_app are never shadowed.
    @app.exception_handler(404)
    async def spa(request: Request, exc: HTTPException):
        path = request.url.path.lstrip("/")
        if request.method != "GET" or path == "api" or path.startswith("api/") or not (STATIC / "index.html").exists():
            return await http_exception_handler(request, exc)
        f = (STATIC / path).resolve()
        return FileResponse(f if f.is_file() and f.is_relative_to(STATIC.resolve()) else STATIC / "index.html")

    return app
