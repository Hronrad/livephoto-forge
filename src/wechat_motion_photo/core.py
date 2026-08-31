from __future__ import annotations

import json
import re
import shutil
import struct
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


class ForgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class TemplateProfile:
    make: str
    model: str
    user_comment: str
    photo_width: int
    photo_height: int
    video_width: int
    video_height: int
    video_codec: str
    video_duration: float
    video_fps: float
    presentation_timestamp_us: int
    video_length: int
    trailer_length: int

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class BuildOptions:
    start: float = 0.0
    duration: float | None = None
    key_time: float | None = None
    crop_mode: str = "crop"
    cover_rotation: int = 0
    video_rotation: int = 0
    crf: int = 18


@dataclass(frozen=True)
class BuildResult:
    output: Path
    profile: TemplateProfile
    video_length: int
    trailer_length: int
    sha256: str


Log = Callable[[str], None]


def _run(args: Sequence[str], *, capture: bool = False) -> str:
    try:
        completed = subprocess.run(
            list(args),
            check=True,
            text=True,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise ForgeError(f"Missing dependency: {args[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "command failed").strip()
        raise ForgeError(f"{Path(args[0]).name} failed: {detail}") from exc
    return completed.stdout if capture else ""


def check_dependencies() -> list[str]:
    return [
        name for name in ("ffmpeg", "ffprobe", "exiftool") if not shutil.which(name)
    ]


def _exif_json(path: Path, *tags: str) -> dict[str, object]:
    text = _run(["exiftool", "-j", "-n", *tags, str(path)], capture=True)
    rows = json.loads(text)
    if not rows:
        raise ForgeError(f"ExifTool returned no metadata for {path}")
    return rows[0]


def _extract_vendor_trailer(data: bytes) -> bytes:
    start = max(0, len(data) - 16384)
    for pos in range(start, len(data) - 3):
        declared = int.from_bytes(data[pos : pos + 4], "big")
        if 32 <= declared == len(data) - pos:
            return data[pos:]
    raise ForgeError("Template has no recognizable OPLUS/OnePlus vendor trailer")


def _replace_required(pattern: str, replacement: str, text: str, label: str) -> str:
    result, count = re.subn(pattern, replacement, text)
    if count == 0:
        raise ForgeError(f"Template XMP is missing required field: {label}")
    return result


def _ffprobe(path: Path) -> dict[str, object]:
    return json.loads(
        _run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path),
            ],
            capture=True,
        )
    )


def _fps(value: str | None) -> float:
    if not value or value == "0/0":
        return 30.0
    numerator, denominator = value.split("/", 1)
    return float(numerator) / float(denominator)


def inspect_template(template: str | Path) -> TemplateProfile:
    template = Path(template)
    if not template.is_file():
        raise ForgeError(f"Template not found: {template}")
    data = template.read_bytes()
    trailer = _extract_vendor_trailer(data)
    tags = _exif_json(
        template,
        "-Make",
        "-Model",
        "-UserComment",
        "-ImageWidth",
        "-ImageHeight",
        "-VideoLength",
        "-MotionPhotoPresentationTimestampUs",
        "-OLivePhotoVersion",
        "-MotionPhotoOwner",
    )
    if (
        int(tags.get("OLivePhotoVersion", 0)) != 2
        or tags.get("MotionPhotoOwner") != "oplus"
    ):
        raise ForgeError("Template is not an OPLUS O-Live Photo v2 file")
    video_length = int(tags.get("VideoLength", 0))
    if video_length <= 0 or video_length + len(trailer) >= len(data):
        raise ForgeError("Template VideoLength is invalid")
    payload_start = len(data) - video_length - len(trailer)
    video = data[payload_start : payload_start + video_length]
    if b"ftyp" not in video[:64]:
        raise ForgeError("Template embedded payload is not MP4")
    with tempfile.TemporaryDirectory(prefix="wechat-live-inspect-") as td:
        video_path = Path(td) / "template.mp4"
        video_path.write_bytes(video)
        probe = _ffprobe(video_path)
    video_stream = next(
        (
            item
            for item in probe.get("streams", [])
            if item.get("codec_type") == "video"
        ),
        None,
    )
    if not video_stream:
        raise ForgeError("Template embedded MP4 has no video stream")
    return TemplateProfile(
        make=str(tags.get("Make", "OPPO")),
        model=str(tags.get("Model", "OPLUS device")),
        user_comment=str(tags.get("UserComment", "oplus_8388640")),
        photo_width=int(tags["ImageWidth"]),
        photo_height=int(tags["ImageHeight"]),
        video_width=int(video_stream["width"]),
        video_height=int(video_stream["height"]),
        video_codec=str(video_stream.get("codec_name", "hevc")),
        video_duration=float(probe.get("format", {}).get("duration", 2.1)),
        video_fps=_fps(video_stream.get("avg_frame_rate")),
        presentation_timestamp_us=int(
            tags.get("MotionPhotoPresentationTimestampUs", 0)
        ),
        video_length=video_length,
        trailer_length=len(trailer),
    )


def _image_dimensions(path: Path) -> tuple[int, int]:
    tags = _exif_json(path, "-ImageWidth", "-ImageHeight")
    return int(tags["ImageWidth"]), int(tags["ImageHeight"])


def _target_dimensions(
    width: int, height: int, template_width: int, template_height: int
) -> tuple[int, int]:
    long_side = max(template_width, template_height)
    short_side = min(template_width, template_height)
    return (long_side, short_side) if width >= height else (short_side, long_side)


def _rotation_filter(degrees: int) -> list[str]:
    normalized = degrees % 360
    if normalized == 0:
        return []
    if normalized == 90:
        return ["transpose=clock"]
    if normalized == 180:
        return ["hflip", "vflip"]
    if normalized == 270:
        return ["transpose=cclock"]
    raise ForgeError("Rotation must be 0, 90, 180 or 270 degrees")


def _sizing_filter(width: int, height: int, mode: str) -> str:
    if mode == "crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height}"
        )
    if mode == "fit":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"
        )
    raise ForgeError("crop_mode must be 'crop' or 'fit'")


def _build_mpf_segment(image_size: int) -> bytes:
    tiff = b"MM\x00\x2a\x00\x00\x00\x08"
    entries = b""
    entries += struct.pack(">HHI", 0xB000, 7, 4) + b"0100"
    entries += struct.pack(">HHI", 0xB001, 4, 1) + struct.pack(">I", 1)
    mpentry_offset = 8 + 2 + 3 * 12 + 4
    entries += struct.pack(">HHII", 0xB002, 7, 16, mpentry_offset)
    ifd = struct.pack(">H", 3) + entries + struct.pack(">I", 0)
    mp_entry = struct.pack(">IIIHH", 0x00030000, image_size, 0, 0, 0)
    body = b"MPF\x00" + tiff + ifd + mp_entry
    return b"\xff\xe2" + struct.pack(">H", len(body) + 2) + body


def _app_insertion_point(jpeg: bytes) -> int:
    if not jpeg.startswith(b"\xff\xd8"):
        raise ForgeError("Processed cover is not JPEG")
    pos, last_app_end = 2, 2
    while pos + 3 < len(jpeg):
        while pos + 1 < len(jpeg) and jpeg[pos : pos + 2] == b"\xff\xff":
            pos += 1
        if jpeg[pos] != 0xFF:
            break
        marker = jpeg[pos + 1]
        if marker in (0xDA, 0xD9) or (
            0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC)
        ):
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        segment_length = int.from_bytes(jpeg[pos + 2 : pos + 4], "big")
        if segment_length < 2 or pos + 2 + segment_length > len(jpeg):
            break
        pos += 2 + segment_length
        if 0xE0 <= marker <= 0xEF:
            last_app_end = pos
    return last_app_end


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _prepare_xmp(
    template: Path, video_length: int, trailer_length: int, timestamp_us: int
) -> str:
    xmp = _run(["exiftool", "-b", "-XMP", str(template)], capture=True)
    xmp = _replace_required(
        r'GCamera:MotionPhotoPresentationTimestampUs="\d+"',
        f'GCamera:MotionPhotoPresentationTimestampUs="{timestamp_us}"',
        xmp,
        "GCamera:MotionPhotoPresentationTimestampUs",
    )
    xmp = _replace_required(
        r'OpCamera:MotionPhotoPrimaryPresentationTimestampUs="\d+"',
        f'OpCamera:MotionPhotoPrimaryPresentationTimestampUs="{timestamp_us}"',
        xmp,
        "OpCamera:MotionPhotoPrimaryPresentationTimestampUs",
    )
    xmp = _replace_required(
        r'OpCamera:VideoLength="\d+"',
        f'OpCamera:VideoLength="{video_length}"',
        xmp,
        "OpCamera:VideoLength",
    )
    return _replace_required(
        r'Item:Length="\d+"',
        f'Item:Length="{video_length + trailer_length}"',
        xmp,
        "Container Item:Length",
    )


def _transcode_cover(
    source: Path, output: Path, target: tuple[int, int], options: BuildOptions
) -> None:
    filters = _rotation_filter(options.cover_rotation)
    filters.append(_sizing_filter(*target, options.crop_mode))
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-vf",
            ",".join(filters),
            "-frames:v",
            "1",
            "-q:v",
            "1",
            str(output),
        ]
    )


def _transcode_video(
    source: Path,
    output: Path,
    target: tuple[int, int],
    profile: TemplateProfile,
    duration: float,
    options: BuildOptions,
) -> None:
    filters = _rotation_filter(options.video_rotation)
    filters.extend(
        [
            _sizing_filter(*target, options.crop_mode),
            f"fps={max(1, round(profile.video_fps))}",
        ]
    )
    codec_args = (
        ["-c:v", "libx265", "-tag:v", "hvc1"]
        if profile.video_codec == "hevc"
        else ["-c:v", "libx264", "-tag:v", "avc1"]
    )
    _run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{options.start:.6f}",
            "-i",
            str(source),
            "-t",
            f"{duration:.6f}",
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-vf",
            ",".join(filters),
            *codec_args,
            "-crf",
            str(options.crf),
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-color_range",
            "pc",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-map_metadata",
            "-1",
            "-movflags",
            "+faststart",
            "-brand",
            "mp42",
            str(output),
        ]
    )


def _write_metadata(
    cover: Path,
    template: Path,
    xmp_file: Path,
    output: Path,
    width: int,
    height: int,
    profile: TemplateProfile,
) -> None:
    shutil.copyfile(cover, output)
    _run(
        [
            "exiftool",
            "-overwrite_original",
            "-XMP:all=",
            "-MPF:all=",
            "-Trailer:all=",
            "-EXIF:all=",
            "-IPTC:all=",
            "-Photoshop:all=",
            str(output),
        ]
    )
    _run(
        [
            "exiftool",
            "-overwrite_original",
            "-TagsFromFile",
            str(template),
            "-EXIF:all",
            "-ICC_Profile",
            str(output),
        ]
    )
    now = datetime.now().astimezone().strftime("%Y:%m:%d %H:%M:%S")
    _run(
        [
            "exiftool",
            "-overwrite_original",
            f"-XMP<={xmp_file}",
            "-GPS:all=",
            f"-EXIF:UserComment={profile.user_comment}",
            f"-EXIF:Make={profile.make}",
            f"-EXIF:Model={profile.model}",
            f"-IFD0:ImageWidth={width}",
            f"-IFD0:ImageHeight={height}",
            f"-ExifIFD:ExifImageWidth={width}",
            f"-ExifIFD:ExifImageHeight={height}",
            "-IFD0:Orientation#=1",
            f"-IFD0:ModifyDate={now}",
            f"-ExifIFD:DateTimeOriginal={now}",
            f"-ExifIFD:CreateDate={now}",
            str(output),
        ]
    )


def _validate(output: Path, expected_video_length: int, trailer_length: int) -> None:
    tags = _exif_json(
        output,
        "-Orientation",
        "-MotionPhoto",
        "-OLivePhotoVersion",
        "-VideoLength",
        "-DirectoryItemLength",
        "-MPImageLength",
    )
    checks = {
        "Orientation": int(tags.get("Orientation", 0)) == 1,
        "MotionPhoto": int(tags.get("MotionPhoto", 0)) == 1,
        "OLivePhotoVersion": int(tags.get("OLivePhotoVersion", 0)) == 2,
        "VideoLength": int(tags.get("VideoLength", -1)) == expected_video_length,
        "DirectoryItemLength": int(tags.get("DirectoryItemLength", -1))
        == expected_video_length + trailer_length,
        "FileLayout": int(tags.get("MPImageLength", -1))
        + expected_video_length
        + trailer_length
        == output.stat().st_size,
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ForgeError("Output validation failed: " + ", ".join(failed))


def build_motion_photo(
    *,
    template: str | Path,
    cover: str | Path,
    video: str | Path,
    output: str | Path,
    options: BuildOptions | None = None,
    log: Log = print,
) -> BuildResult:
    options = options or BuildOptions()
    missing = check_dependencies()
    if missing:
        raise ForgeError("Install required commands first: " + ", ".join(missing))
    template, cover, video, output = map(Path, (template, cover, video, output))
    for path in (template, cover, video):
        if not path.is_file():
            raise ForgeError(f"Input not found: {path}")
    profile = inspect_template(template)
    source_width, source_height = _image_dimensions(cover)
    if options.cover_rotation % 180:
        source_width, source_height = source_height, source_width
    cover_target = _target_dimensions(
        source_width, source_height, profile.photo_width, profile.photo_height
    )
    video_target = _target_dimensions(
        source_width, source_height, profile.video_width, profile.video_height
    )
    duration = (
        options.duration if options.duration is not None else profile.video_duration
    )
    if duration <= 0:
        raise ForgeError("Duration must be positive")
    key_time = (
        options.key_time
        if options.key_time is not None
        else profile.presentation_timestamp_us / 1_000_000
    )
    key_time = min(max(0.0, key_time), duration)
    timestamp_us = round(key_time * 1_000_000)
    trailer = _extract_vendor_trailer(template.read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    log(f"Template: {profile.make} {profile.model}")
    with tempfile.TemporaryDirectory(prefix="wechat-motion-photo-") as td:
        temp = Path(td)
        cover_jpg = temp / "cover.jpg"
        video_mp4 = temp / "motion.mp4"
        metadata_jpg = temp / "metadata.jpg"
        xmp_file = temp / "template.xmp"
        log("[1/4] Processing cover")
        _transcode_cover(cover, cover_jpg, cover_target, options)
        log("[2/4] Processing motion video")
        _transcode_video(video, video_mp4, video_target, profile, duration, options)
        video_bytes = video_mp4.read_bytes()
        xmp_file.write_text(
            _prepare_xmp(template, len(video_bytes), len(trailer), timestamp_us)
        )
        log("[3/4] Cloning phone metadata and vendor trailer")
        _write_metadata(
            cover_jpg,
            template,
            xmp_file,
            metadata_jpg,
            cover_target[0],
            cover_target[1],
            profile,
        )
        jpeg = metadata_jpg.read_bytes()
        probe_mpf = _build_mpf_segment(0)
        mpf = _build_mpf_segment(len(jpeg) + len(probe_mpf))
        insert_at = _app_insertion_point(jpeg)
        output.write_bytes(
            jpeg[:insert_at] + mpf + jpeg[insert_at:] + video_bytes + trailer
        )
    log("[4/4] Validating output")
    _validate(output, len(video_bytes), len(trailer))
    return BuildResult(output, profile, len(video_bytes), len(trailer), _sha256(output))
