import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Literal

from cryptography.fernet import Fernet

from .config import Env

SCHEMA = """
create table if not exists settings (key text primary key, value text not null);
create table if not exists styles (
  id text primary key, yaml text, preview_image_path text,
  hidden integer not null default 0, sort_order integer);
create table if not exists jobs (
  id text primary key, source_asset_id text not null, media_type text not null,
  style_id text, custom_prompt text, provider_id text, provider_model text,
  variations integer not null default 1, clip_start_s real, clip_end_s real,
  segmented integer not null default 0, status text not null default 'queued',
  error_code text, error_message text, cost_estimate_usd real,
  created_at text not null default (datetime('now')), finished_at text);
create table if not exists results (
  id text primary key, job_id text not null references jobs(id), "index" integer not null,
  file_path text, mime text, width integer, height integer, duration_s real,
  saved_asset_id text, saved_at text, discarded integer not null default 0,
  save_step text, save_error text);
"""

PROVIDERS = ("gemini", "openai", "stability", "runway", "luma", "comfyui")
# env var -> setting key
ENV_MAP = {
    **{f"{p.upper()}_API_KEY": f"providers.{p}.api_key" for p in PROVIDERS if p != "comfyui"},
    "COMFYUI_URL": "providers.comfyui.url",
}
KEY_TO_ENV = {v: k for k, v in ENV_MAP.items()}

DEFAULTS: dict[str, Any] = {
    "default_provider.image": "gemini",
    "default_provider.video": None,
    "save.stack_primary": "original",
    "save.album": "Remixes",
    "save.tag": None,
    "photo.max_px": 2048,
    "photo.jpeg_quality": 92,
    "photo.source": "original",
    "video.max_height": 1080,
    "video.keep_audio": True,
    "cleanup.days": 14,
    "styles.category_order": None,
    **{f"providers.{p}.{f}": None for p in PROVIDERS for f in ("api_key", "model", "url")},
    **{f"providers.{p}.enabled": False for p in PROVIDERS},
}
SECRET_KEYS = {f"providers.{p}.api_key" for p in PROVIDERS}
_PROVIDER_KEY = re.compile(r"providers\.(" + "|".join(PROVIDERS) + r")\.[\w.]+$")


class ReadOnlySetting(Exception):
    pass


def connect(data_dir: Path) -> sqlite3.Connection:
    data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data_dir / "app.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    conn.executescript(SCHEMA)
    return conn


def _fernet(data_dir: Path) -> Fernet:
    p = data_dir / "secret.key"
    if not p.exists():
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(Fernet.generate_key())
    return Fernet(p.read_bytes())


class Settings:
    def __init__(self, conn: sqlite3.Connection, env: Env, data_dir: Path):
        self.conn, self.env, self._fernet = conn, env, _fernet(data_dir)

    def _env(self, key: str) -> str | None:
        name = KEY_TO_ENV.get(key)
        return getattr(self.env, name) if name else None

    def _stored(self, key: str) -> tuple[bool, Any]:
        row = self.conn.execute("select value from settings where key=?", (key,)).fetchone()
        if not row:
            return False, None
        v = json.loads(row[0])
        return True, (self._fernet.decrypt(v.encode()).decode() if key in SECRET_KEYS and v else v)

    def _check(self, key: str) -> None:
        if key not in DEFAULTS and not _PROVIDER_KEY.match(key):
            raise KeyError(key)

    def source(self, key: str) -> Literal["env", "db", "default"]:
        self._check(key)
        if self._env(key):
            return "env"
        return "db" if self._stored(key)[0] else "default"

    def get(self, key: str) -> Any:
        self._check(key)
        if v := self._env(key):
            return v
        found, v = self._stored(key)
        if found:
            return v
        if key.endswith(".enabled") and key in DEFAULTS:
            p = key.split(".")[1]
            return bool(self._env(f"providers.{p}.api_key") or self._env(f"providers.{p}.url"))
        return DEFAULTS.get(key)

    def set(self, key: str, value: Any) -> None:
        self._check(key)
        if self._env(key):
            raise ReadOnlySetting(key)
        if key in SECRET_KEYS and value:
            value = self._fernet.encrypt(value.encode()).decode()
        self.conn.execute(
            "insert into settings(key, value) values(?, ?) on conflict(key) do update set value=excluded.value",
            (key, json.dumps(value)),
        )
        self.conn.commit()

    def public(self) -> dict:
        extra = {r[0] for r in self.conn.execute("select key from settings")}
        out = {}
        for k in sorted(DEFAULTS.keys() | extra):
            if k in SECRET_KEYS:
                out[k] = {"set": bool(self.get(k)), "source": self.source(k)}
            else:
                out[k] = self.get(k)
        return out
