import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.media.image import SourceMeta
from app.media.video import MediaError, finalize_video, prepare_video, probe

SIZE = "320x180"


def ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def tags(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_format", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)["format"].get("tags", {})


def make(path: Path, dur: float, fps: int, *, audio=False, codec="libx264", extra=()) -> Path:
    args = ["-f", "lavfi", "-i", f"testsrc=size={SIZE}:rate={fps}:duration={dur}"]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=duration={dur}"]
    ff(*args, "-c:v", codec, "-pix_fmt", "yuv420p", *(["-c:a", "aac"] if audio else []), *extra, str(path))
    return path


META = SourceMeta(datetime(2024, 5, 1, 12, 0, tzinfo=timezone(timedelta(hours=2))), "+02:00", 48.8584, 2.2945)
NOMETA = SourceMeta(None, None, None, None)


async def test_prepare_trims_and_strips(tmp_path):
    src = make(tmp_path / "s.mp4", 10, 30, audio=True, codec="libx265",
               extra=["-metadata", "creation_time=2024-01-01T00:00:00Z"])
    info = await prepare_video(src, tmp_path / "o.mp4", 2, 5, 1080)
    assert info.codec == "h264" and not info.has_audio
    assert info.duration == pytest.approx(3, abs=0.2)
    assert "creation_time" not in tags(tmp_path / "o.mp4")


async def test_prepare_respects_rotation(tmp_path):
    plain = make(tmp_path / "plain.mp4", 2, 30)
    src = tmp_path / "s.mp4"  # Display Matrix rotation, as phones write it
    ff("-display_rotation", "90", "-i", str(plain), "-c", "copy", str(src))
    assert (await probe(src)).rotation in (90, -90, 270)
    info = await prepare_video(src, tmp_path / "o.mp4", 0, 2, 1080)
    assert info.width < info.height and info.rotation == 0


async def test_prepare_scales_short_edge(tmp_path):
    src = make(tmp_path / "s.mp4", 2, 30)
    info = await prepare_video(src, tmp_path / "o.mp4", 0, 2, 90)
    assert min(info.width, info.height) == 90 and info.width % 2 == 0


async def test_finalize_conforms_fps_and_length(tmp_path):
    orig = make(tmp_path / "o.mp4", 5, 30)
    remix = make(tmp_path / "r.mp4", 2.8, 24)
    await finalize_video(remix, orig, tmp_path / "f.mp4", 1, 4, False, NOMETA)
    info = await probe(tmp_path / "f.mp4")
    assert info.fps == pytest.approx(30, abs=0.1)
    assert info.duration == pytest.approx(3.0, abs=0.05)


async def test_finalize_trims_longer_remix(tmp_path):
    orig = make(tmp_path / "o.mp4", 5, 30)
    remix = make(tmp_path / "r.mp4", 4, 30)
    await finalize_video(remix, orig, tmp_path / "f.mp4", 0, 3, False, NOMETA)
    assert (await probe(tmp_path / "f.mp4")).duration == pytest.approx(3.0, abs=0.05)


async def test_finalize_short_remix_keeps_length_and_audio_matches(tmp_path):
    orig = make(tmp_path / "o.mp4", 6, 30, audio=True)
    remix = make(tmp_path / "r.mp4", 2, 30)
    await finalize_video(remix, orig, tmp_path / "f.mp4", 0, 4, True, NOMETA)
    info = await probe(tmp_path / "f.mp4")
    assert info.has_audio and info.duration == pytest.approx(2.0, abs=0.1)


async def test_finalize_muxes_audio(tmp_path):
    orig = make(tmp_path / "o.mp4", 5, 30, audio=True)
    remix = make(tmp_path / "r.mp4", 3, 30)
    await finalize_video(remix, orig, tmp_path / "f.mp4", 1, 4, True, NOMETA)
    info = await probe(tmp_path / "f.mp4")
    assert info.has_audio and info.duration == pytest.approx(3.0, abs=0.1)


async def test_finalize_no_audio_source_keep_on(tmp_path):
    orig = make(tmp_path / "o.mp4", 5, 30)
    remix = make(tmp_path / "r.mp4", 3, 30)
    await finalize_video(remix, orig, tmp_path / "f.mp4", 1, 4, True, NOMETA)
    assert not (await probe(tmp_path / "f.mp4")).has_audio


async def test_finalize_writes_creation_time_and_location(tmp_path):
    orig = make(tmp_path / "o.mp4", 5, 30)
    remix = make(tmp_path / "r.mp4", 3, 30)
    await finalize_video(remix, orig, tmp_path / "f.mp4", 1, 4, False, META)
    t = tags(tmp_path / "f.mp4")
    assert t["creation_time"].startswith("2024-05-01T10:00:00")
    assert t["location"] == "+48.8584+002.2945/"
    assert t["com.apple.quicktime.location.ISO6709"] == "+48.8584+002.2945/"


async def test_finalize_without_meta_skips_fields(tmp_path):
    orig = make(tmp_path / "o.mp4", 5, 30)
    remix = make(tmp_path / "r.mp4", 3, 30)
    await finalize_video(remix, orig, tmp_path / "f.mp4", 1, 4, False, NOMETA)
    t = tags(tmp_path / "f.mp4")
    assert "creation_time" not in t and "location" not in t


async def test_media_error_on_bad_input(tmp_path):
    (tmp_path / "bad.mp4").write_bytes(b"nope")
    with pytest.raises(MediaError):
        await probe(tmp_path / "bad.mp4")
