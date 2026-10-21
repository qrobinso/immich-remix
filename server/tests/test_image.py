import io
from datetime import datetime, timedelta, timezone

import piexif
import pytest
from PIL import Image

from app.media.image import SourceMeta, UnsupportedImage, encode_output, prepare_image, source_meta


def _jpeg(size=(100, 50), exif=None) -> bytes:
    buf = io.BytesIO()
    kw = {"exif": piexif.dump(exif)} if exif else {}
    Image.new("RGB", size, "red").save(buf, "JPEG", **kw)
    return buf.getvalue()


def _open(b: bytes) -> Image.Image:
    return Image.open(io.BytesIO(b))


def test_heic_converted():
    from pillow_heif import register_heif_opener

    register_heif_opener()
    buf = io.BytesIO()
    try:
        Image.new("RGB", (64, 48), "blue").save(buf, "HEIF")
    except Exception as e:  # pragma: no cover
        pytest.skip(f"HEIF encoding unavailable: {e}")
    out = prepare_image(buf.getvalue(), 2048)
    im = _open(out)
    assert im.format == "JPEG" and im.size == (64, 48)


def test_exif_rotation_applied():
    src = _jpeg((100, 50), {"0th": {piexif.ImageIFD.Orientation: 6}})
    assert _open(prepare_image(src, 2048)).size == (50, 100)


def test_resized_to_max():
    assert _open(prepare_image(_jpeg((4000, 3000)), 2048)).size == (2048, 1536)


def test_input_has_no_exif():
    gps = {
        piexif.GPSIFD.GPSLatitudeRef: b"N",
        piexif.GPSIFD.GPSLatitude: ((48, 1), (51, 1), (0, 1)),
    }
    src = _jpeg(exif={"GPS": gps})
    assert piexif.load(src)["GPS"]  # fixture really has GPS
    assert piexif.load(prepare_image(src, 2048))["GPS"] == {}


def test_output_metadata_roundtrip():
    meta = source_meta(
        {
            "exifInfo": {
                "dateTimeOriginal": "2024-05-01T10:00:00.000Z",
                "timeZone": "Europe/Paris",
                "latitude": -33.8567,
                "longitude": 151.2153,
            },
            "fileCreatedAt": "2020-01-01T00:00:00.000Z",
        }
    )
    assert meta.tz == "+02:00"
    out = encode_output(_jpeg(), meta, "Remix: Test · Gemini", 92)
    ex = piexif.load(out)
    assert ex["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2024:05:01 12:00:00"
    assert ex["0th"][piexif.ImageIFD.DateTime] == b"2024:05:01 12:00:00"
    assert ex["Exif"][piexif.ExifIFD.OffsetTimeOriginal] == b"+02:00"
    assert ex["0th"][piexif.ImageIFD.Software] == b"immich-remix"
    assert ex["0th"][piexif.ImageIFD.ImageDescription].decode() == "Remix: Test · Gemini"
    g = ex["GPS"]

    def deg(v):
        return sum(n / d / 60**i for i, (n, d) in enumerate(v))

    assert g[piexif.GPSIFD.GPSLatitudeRef] == b"S" and g[piexif.GPSIFD.GPSLongitudeRef] == b"E"
    assert abs(deg(g[piexif.GPSIFD.GPSLatitude]) - 33.8567) < 1e-5
    assert abs(deg(g[piexif.GPSIFD.GPSLongitude]) - 151.2153) < 1e-5
    assert _open(out).size == (100, 50)


def test_output_without_gps_or_date():
    meta = source_meta({"fileCreatedAt": "2024-05-01T10:00:00Z", "exifInfo": {"timeZone": None}})
    assert meta.taken_at == datetime(2024, 5, 1, 10, tzinfo=timezone.utc)
    assert meta.tz is None and meta.lat is None
    ex = piexif.load(encode_output(_jpeg(), meta, "d", 90))
    assert ex["GPS"] == {}
    assert piexif.ExifIFD.OffsetTimeOriginal not in ex["Exif"]
    assert ex["Exif"][piexif.ExifIFD.DateTimeOriginal] == b"2024:05:01 10:00:00"

    bare = encode_output(_jpeg(), SourceMeta(None, None, None, None), "d", 90)
    ex = piexif.load(bare)
    assert ex["GPS"] == {} and piexif.ExifIFD.DateTimeOriginal not in ex["Exif"]
    assert source_meta({}).taken_at is None


def test_utc_offset_timezone_name():
    m = source_meta({"exifInfo": {"dateTimeOriginal": "2024-05-01T10:00:00Z", "timeZone": "UTC+5:30"}})
    assert m.tz == "+05:30" and m.taken_at.utcoffset() == timedelta(hours=5, minutes=30)


def test_unsupported_raises():
    with pytest.raises(UnsupportedImage):
        prepare_image(b"not an image", 2048)
