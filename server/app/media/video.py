import asyncio
import json
from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

from app.media.image import SourceMeta


class MediaError(Exception):
    """ffmpeg/ffprobe failed; message is the tail of stderr."""


@dataclass
class VideoInfo:
    duration: float
    fps: float
    width: int
    height: int
    rotation: int
    has_audio: bool
    codec: str
    fps_expr: str = "30/1"  # ffprobe's exact rational, for ffmpeg -r


async def _run(*args: str) -> bytes:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise MediaError(err.decode(errors="replace")[-2000:])
    return out


async def _ffmpeg(*args: str) -> None:
    await _run("ffmpeg", "-v", "error", "-y", *args)


def _frac(s: str) -> float:
    n, _, d = s.partition("/")
    return float(n) / float(d or 1) if float(d or 1) else 0.0


async def probe(path: Path) -> VideoInfo:
    out = await _run("ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path))
    data = json.loads(out)
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if v is None:
        raise MediaError("no video stream")
    rot = next((sd["rotation"] for sd in v.get("side_data_list", []) if "rotation" in sd), None)
    if rot is None:
        rot = v.get("tags", {}).get("rotate", 0)
    expr = v.get("avg_frame_rate", "0/0")
    if _frac(expr) == 0:
        expr = v.get("r_frame_rate", "0/1")
    return VideoInfo(
        duration=float(data["format"].get("duration") or v.get("duration") or 0),
        fps=_frac(expr),
        width=int(v["width"]),
        height=int(v["height"]),
        rotation=int(float(rot)),
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        codec=v.get("codec_name", ""),
        fps_expr=expr,
    )


_X264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


async def prepare_video(src: Path, out: Path, start: float, end: float, max_height: int) -> VideoInfo:
    h = max_height
    # short edge capped at max_height, aspect kept, even dims (-2); autorotate is ffmpeg's default
    vf = f"scale=w='if(lt(iw,ih),min(iw,{h}),-2)':h='if(lt(iw,ih),-2,min(ih,{h}))'"
    await _ffmpeg("-ss", str(start), "-i", str(src), "-t", str(end - start),
                  "-vf", vf, *_X264, "-an", "-map_metadata", "-1", str(out))
    return await probe(out)


def _iso6709(lat: float, lon: float) -> str:
    return f"{lat:+08.4f}{lon:+09.4f}/"


async def finalize_video(
    remix: Path, original: Path, out: Path, start: float, end: float, keep_audio: bool, meta: SourceMeta
) -> None:
    target = end - start
    orig, rmx = await probe(original), await probe(remix)
    gap = target - rmx.duration
    vf = f"tpad=stop_mode=clone:stop_duration={gap:.3f}" if 0 < gap < 0.5 else None
    use_audio = keep_audio and orig.has_audio

    args = ["-i", str(remix)]
    if use_audio:
        args += ["-ss", str(start), "-t", str(target), "-i", str(original)]
    args += ["-map", "0:v:0"] + (["-map", "1:a:0"] if use_audio else [])
    if vf:
        args += ["-vf", vf]
    # -t trims a longer remix; -shortest cuts audio to a remix that is much shorter
    args += ["-r", orig.fps_expr, *_X264, "-t", str(target)]
    if use_audio:
        args += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    args += ["-map_metadata", "-1"]
    if meta.taken_at:
        args += ["-metadata", "creation_time=" + meta.taken_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
    if meta.lat is not None and meta.lon is not None:
        loc = _iso6709(meta.lat, meta.lon)
        args += ["-metadata", f"location={loc}", "-metadata", f"com.apple.quicktime.location.ISO6709={loc}"]
    args += ["-movflags", "+faststart+use_metadata_tags", str(out)]
    await _ffmpeg(*args)
