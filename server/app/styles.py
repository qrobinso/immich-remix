import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from .providers.base import MediaType

CATEGORIES = [
    ("illustrated", "Illustrated"),
    ("painted", "Painted and drawn"),
    ("collectibles", "Collectibles"),
    ("photo_looks", "Photo looks"),
    ("occasions", "Occasions"),
    ("scenes", "Scenes"),
]
KEEP = "Keep every person, face, pose and the overall composition recognizable."
BUILTIN_DIR = Path(__file__).resolve().parents[1] / "styles"  # /app/styles in Docker
ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")  # ids become file names


class StyleForm(BaseModel):
    """The editable fields (design doc: Builder's calls)."""

    id: str = Field(pattern=ID_RE.pattern)
    name: str = Field(min_length=1)
    category: str
    media_types: set[MediaType] = Field(min_length=1)
    prompt: str = Field(min_length=1)
    negative_prompt: str | None = None
    strength: float | None = Field(default=None, ge=0, le=1)
    default_provider: dict[MediaType, str] = {}
    preview_prompt: str | None = None
    status_text: str | None = None

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        if v not in dict(CATEGORIES):
            raise ValueError("unknown category")
        return v


class Style(StyleForm):
    providers: dict[str, dict] = {}  # per-provider overrides, hand-edited in YAML only
    preview_image: str | None = None
    builtin: bool = False
    hidden: bool = False
    sort_order: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _flatten_preview(cls, d: Any) -> Any:
        # `segmentable` and `preview.video` are ignored (extra keys); preview.image is kept.
        if isinstance(d, dict) and isinstance(d.get("preview"), dict):
            d = {**d, "preview_image": d["preview"].get("image")}
        return d


def build_prompt(style: Style | None, custom: str | None) -> tuple[str, str | None]:
    if style is not None:
        return style.prompt, style.negative_prompt
    if not custom or not custom.strip():
        raise ValueError("a style or a custom prompt is required")
    return f"{custom.strip()} {KEEP}", None


def build_edit_prompt(text: str, marked: bool) -> str:
    where = (" The red circle marks the area to change; leave no trace of the circle in the result." if marked else "")
    return f"Edit this image: {text.strip()}.{where} Change only what is asked and keep everything else exactly the same."


def _read(d: Path) -> dict[str, Style]:
    out = {}
    for f in sorted(d.glob("*.yaml")) if d.is_dir() else []:
        try:
            s = Style.model_validate(yaml.safe_load(f.read_text()))
        except Exception:  # a broken user file must not take the library down
            continue
        if s.id == f.stem:
            out[s.id] = s
    return out


class StyleLibrary:
    """Reads the YAML dirs on every call (about 45 tiny files); hidden/order live in the `styles` table."""

    def __init__(self, builtin_dir: Path, user_dir: Path, conn: sqlite3.Connection):
        self.builtin_dir, self.user_dir, self.conn = builtin_dir, user_dir, conn

    def all(self) -> list[Style]:
        builtin, user = _read(self.builtin_dir), _read(self.user_dir)
        meta = {r["id"]: r for r in self.conn.execute("select id, hidden, sort_order from styles")}
        out = []
        for id, s in {**builtin, **user}.items():
            m = meta.get(id)
            out.append(s.model_copy(update={
                "builtin": id in builtin and id not in user,
                "hidden": bool(m and m["hidden"]),
                "sort_order": m["sort_order"] if m else None,
            }))
        return sorted(out, key=lambda s: (s.sort_order is None, s.sort_order or 0))  # stable: ties keep file order

    def get(self, id: str) -> Style:
        for s in self.all():
            if s.id == id:
                return s
        raise KeyError(id)

    def has_user_file(self, id: str) -> bool:
        return (self.user_dir / f"{id}.yaml").is_file()

    def save_user(self, form: StyleForm) -> Style:
        try:
            providers = self.get(form.id).providers  # form can't edit overrides; keep them
        except KeyError:
            providers = {}
        data = form.model_dump(mode="json", exclude_none=True, exclude_defaults=False)
        data["media_types"] = sorted(data["media_types"])
        if KEEP not in data["prompt"]:  # every style prompt keeps people recognizable
            data["prompt"] = f"{data['prompt'].strip()} {KEEP}"
        if providers:
            data["providers"] = providers
        self.user_dir.mkdir(parents=True, exist_ok=True)
        (self.user_dir / f"{form.id}.yaml").write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        return self.get(form.id)

    def delete_user(self, id: str) -> None:
        (self.user_dir / f"{id}.yaml").unlink()

    def set_hidden(self, id: str, hidden: bool) -> None:
        with self.conn:
            self.conn.execute(
                "insert into styles(id, hidden) values(?, ?) on conflict(id) do update set hidden=excluded.hidden",
                (id, int(hidden)))

    def set_order(self, ids: list[str]) -> None:
        with self.conn:
            for i, id in enumerate(ids):
                self.conn.execute(
                    "insert into styles(id, sort_order) values(?, ?) on conflict(id) do update set sort_order=excluded.sort_order",
                    (id, i))
