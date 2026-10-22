import io
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

import piexif
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener

register_heif_opener()


class UnsupportedImage(Exception):
    pass


@dataclass
class SourceMeta:
    taken_at: datetime | None  # aware (in the source zone) when known
    tz: str | None  # "+02:00"
    lat: float | None
    lon: float | None


def _fmt_offset(td: timedelta) -> str:
    mins = int(td.total_seconds() // 60)
    sign = "-" if mins < 0 else "+"
    return f"{sign}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"


def _zone(name: str | None) -> tzinfo | None:
    if not name:
        return None
    m = re.fullmatch(r"(?:UTC|GMT)?\s*([+-])(\d{1,2})(?::?(\d{2}))?", name.strip())
    if m:
        off = timedelta(hours=int(m[2]), minutes=int(m[3] or 0))
        return timezone(-off if m[1] == "-" else off)
    if name.strip().upper() in ("UTC", "GMT"):
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return None


def source_meta(asset: dict) -> SourceMeta:
    exif = asset.get("exifInfo") or {}
    raw = exif.get("dateTimeOriginal") or asset.get("fileCreatedAt")
    taken = None
    if raw:
        try:
            taken = datetime.fromisoformat(raw)
        except ValueError:
            pass
    tz = None
    zone = _zone(exif.get("timeZone"))
    if taken and zone:
        if taken.tzinfo is None:
            taken = taken.replace(tzinfo=timezone.utc)
        taken = taken.astimezone(zone)
        tz = _fmt_offset(taken.utcoffset())
    return SourceMeta(taken, tz, exif.get("latitude"), exif.get("longitude"))


def prepare_image(data: bytes, max_px: int) -> bytes:
    try:
        im = Image.open(io.BytesIO(data))
        im = ImageOps.exif_transpose(im)
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, "white")
            bg.paste(im, mask=im.getchannel("A"))
            im = bg
        else:
            im = im.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as e:
        raise UnsupportedImage(str(e)) from e
    im.thumbnail((max_px, max_px), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=95)  # no exif/icc passed: metadata is stripped
    return out.getvalue()


def mark_spot(jpeg: bytes, x: float, y: float) -> bytes:
    """Draw a red ring at (x, y), given as fractions of width and height, so an edit model knows where to look."""
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    w, h = im.size
    r, cx, cy = max(4, round(min(w, h) * 0.08)), x * w, y * h
    ImageDraw.Draw(im).ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 0, 0), width=max(2, r // 4))
    out = io.BytesIO()
    im.save(out, "JPEG", quality=95)
    return out.getvalue()


def _dms(v: float) -> tuple:
    v = abs(v)
    d = int(v)
    m = int((v - d) * 60)
    s = round(((v - d) * 60 - m) * 60 * 10000)
    return ((d, 1), (m, 1), (s, 10000))


def encode_output(data: bytes, meta: SourceMeta, description: str, quality: int) -> bytes:
    zeroth = {
        piexif.ImageIFD.Software: b"immich-remix",
        piexif.ImageIFD.ImageDescription: description.encode("utf-8"),
    }
    exif, gps = {}, {}
    if meta.taken_at:
        ts = meta.taken_at.strftime("%Y:%m:%d %H:%M:%S").encode()
        zeroth[piexif.ImageIFD.DateTime] = exif[piexif.ExifIFD.DateTimeOriginal] = ts
        if meta.tz:
            exif[piexif.ExifIFD.OffsetTimeOriginal] = meta.tz.encode()
    if meta.lat is not None and meta.lon is not None:
        gps = {
            piexif.GPSIFD.GPSLatitudeRef: b"N" if meta.lat >= 0 else b"S",
            piexif.GPSIFD.GPSLatitude: _dms(meta.lat),
            piexif.GPSIFD.GPSLongitudeRef: b"E" if meta.lon >= 0 else b"W",
            piexif.GPSIFD.GPSLongitude: _dms(meta.lon),
        }
    im = Image.open(io.BytesIO(data)).convert("RGB")
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality, exif=piexif.dump({"0th": zeroth, "Exif": exif, "GPS": gps}))
    return out.getvalue()
