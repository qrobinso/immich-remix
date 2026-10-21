import io
import os
from pathlib import Path

from PIL import Image, ImageOps

from .providers.base import Provider
from .styles import Style

QUALITY = 82


def _save(im: Image.Image, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".tmp")
    im.save(tmp, format="WEBP", quality=QUALITY)
    os.replace(tmp, dest)  # atomic: readers never see a half-written file


def write_preview(data: bytes, dest_dir: Path, style_id: str) -> None:
    """Card: center-cropped 600x600. Full: long edge 1600, never upscaled."""
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    dest_dir.mkdir(parents=True, exist_ok=True)
    _save(ImageOps.fit(im, (600, 600), Image.LANCZOS), dest_dir / f"{style_id}.card.webp")
    full = im.copy()
    full.thumbnail((1600, 1600), Image.LANCZOS)  # thumbnail only shrinks
    _save(full, dest_dir / f"{style_id}.full.webp")


def find_preview(dirs: list[Path], style_id: str, kind: str = "card") -> Path | None:
    """First existing file among dirs (user dir first)."""
    return next((p for d in dirs if (p := d / f"{style_id}.{kind}.webp").is_file()), None)


async def generate_preview(style: Style, provider: Provider) -> bytes:
    return await provider.generate(style.preview_prompt or style.prompt)


def estimate_preview_cost(provider: Provider) -> float | None:
    return (provider.price_per_output or {}).get("image")
