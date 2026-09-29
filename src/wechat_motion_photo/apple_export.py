"""Apple Live Photo resources for direct iOS import or macOS Photos."""
from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

from .apple_live import inspect_live_jpeg, inspect_live_mov, write_live_jpeg, write_live_mov
from .apple_hdr import inspect_live_hdr_heic, write_live_hdr_heic
from .core import ForgeError, _hdr_colors, extract_first_frame


def _video_seconds(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise ForgeError("无法读取 Apple 实况视频时长")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ForgeError("无法读取 Apple 实况视频时长") from exc
    if duration <= 0:
        raise ForgeError("视频时长必须大于零")
    return duration


def build_apple_live_pair(
    *, video: Path, cover: Path | None, work: Path,
    start: float, duration: float | None, key_time: float | None,
    preserve_hdr_still: bool = False,
) -> tuple[Path, Path]:
    """Return matched HEIC-or-JPG/MOV resources."""
    if video.stat().st_size > 128 * 1024 * 1024:
        raise ForgeError("Apple 实验输出目前支持不超过 128 MB 的短视频")
    source_seconds = _video_seconds(video)
    if start < 0 or start >= source_seconds:
        raise ForgeError("开始时间必须位于视频内")
    clip_seconds = min(duration if duration is not None else 3.0, 3.0, source_seconds - start)
    if clip_seconds <= 0:
        raise ForgeError("Apple 实况视频时长必须大于零")
    if key_time is not None and not 0 <= key_time < clip_seconds:
        raise ForgeError("封面时间必须位于所选视频片段内")

    remuxed = work / "apple-source.mov"
    command = [
        "ffmpeg", "-y", "-v", "error", "-ss", str(start), "-i", str(video),
        "-t", str(clip_seconds), "-map", "0:v:0", "-map", "0:a?",
        "-c", "copy", "-avoid_negative_ts", "make_zero", str(remuxed),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode or not remuxed.is_file() or remuxed.stat().st_size == 0:
        raise ForgeError("无法保留原视频流生成 Apple 配对 MOV：" + (result.stderr.strip() or "视频格式不受支持"))
    actual_seconds = _video_seconds(remuxed)
    still_time = key_time if key_time is not None else 0.0
    if still_time >= actual_seconds:
        raise ForgeError("封面时间超出了实际输出视频")
    poster = cover
    if poster is not None and poster.suffix.lower() in {".heic", ".heif", ".avif"}:
        raise ForgeError("Apple 实验输出暂不支持 HEIC/AVIF 封面；请上传 JPG 或 PNG")
    hdr_still = preserve_hdr_still and poster is None and _hdr_colors(remuxed) is not None
    if poster is None and not hdr_still:
        poster = work / "apple-poster.png"
        extract_first_frame(remuxed, poster, still_time)

    stem = "IMG_Apple_Live"
    still = work / f"{stem}.{'HEIC' if hdr_still else 'JPG'}"
    movie = work / f"{stem}.MOV"
    asset_id = str(uuid.uuid4()).upper()
    try:
        if hdr_still:
            write_live_hdr_heic(remuxed, still, asset_id, still_time)
        else:
            write_live_jpeg(poster, still, asset_id)
        write_live_mov(remuxed, movie, asset_id, still_time, actual_seconds)
        still_id = inspect_live_hdr_heic(still)[0] if hdr_still else inspect_live_jpeg(still)
        if still_id != asset_id or inspect_live_mov(movie).asset_id != asset_id:
            raise ForgeError("Apple 实况照片配对验证失败")
    except (OSError, ValueError) as exc:
        raise ForgeError(f"Apple 实况照片生成失败：{exc}") from exc
    return still, movie
