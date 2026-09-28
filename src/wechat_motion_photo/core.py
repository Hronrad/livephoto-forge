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
    format: str
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
class SubmissionProfile:
    format: str
    make: str
    model: str
    photo_width: int
    photo_height: int
    video_width: int
    video_height: int
    video_codec: str
    video_duration: float
    video_fps: float
    video_length: int
    video_offset: int

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


def _extract_honor_trailer(data: bytes) -> tuple[bytes, int]:
    """Return HONOR's fixed-width trailer and the embedded MP4 length.

    HONOR motion photos end in three 20-byte ASCII fields.  The last field is
    ``LIVE_<length>`` and counts the MP4 plus the first 20 bytes of the
    trailer, rather than just the MP4 payload.
    """
    if len(data) < 60:
        raise ForgeError("Template has no recognizable HONOR motion-photo trailer")
    trailer = data[-60:]
    try:
        first = trailer[:20].decode("ascii").rstrip()
        trailer[20:40].decode("ascii")
        live = trailer[40:60].decode("ascii").rstrip()
    except UnicodeDecodeError as exc:
        raise ForgeError(
            "Template has no recognizable HONOR motion-photo trailer"
        ) from exc
    match = re.fullmatch(r"LIVE_(\d+)", live)
    if not re.match(r"^v\d+_f\d+", first) or not match:
        raise ForgeError("Template has no recognizable HONOR motion-photo trailer")
    video_length = int(match.group(1)) - 20
    payload_start = len(data) - len(trailer) - video_length
    if video_length <= 0 or payload_start < 0:
        raise ForgeError("Template HONOR video length is invalid")
    if data[payload_start + 4 : payload_start + 8] != b"ftyp":
        raise ForgeError("Template HONOR embedded payload is not MP4")
    return trailer, video_length


def _rewrite_honor_trailer(trailer: bytes, video_length: int) -> bytes:
    if len(trailer) != 60:
        raise ForgeError("Template HONOR trailer length is invalid")
    live = f"LIVE_{video_length + 20}".encode("ascii")
    if len(live) > 20:
        raise ForgeError("Generated video is too large for the HONOR trailer")
    return trailer[:40] + live.ljust(20, b" ")


def _build_huawei_trailer(
    video_length: int, cover_frame: int, total_frames: int
) -> bytes:
    """Build the 60-byte HUAWEI/HONOR LIVE_ trailer used by open tools."""
    trailer = bytearray(b" " * 60)
    first = f"v6_f{max(0, cover_frame)}".encode("ascii")[:6]
    timing = f"{max(0, cover_frame)}:{max(1, total_frames)}".encode("ascii")[:8]
    live = f"LIVE_{video_length + 20}".encode("ascii")
    if len(live) > 20:
        raise ForgeError("Generated video is too large for the HUAWEI trailer")
    trailer[: len(first)] = first
    trailer[20 : 20 + len(timing)] = timing
    trailer[40 : 40 + len(live)] = live
    return bytes(trailer)


def _build_samsung_sef(video: bytes) -> bytes:
    """Build the legacy one-field Samsung SEF trailer used by Galaxy S7."""
    name = b"MotionPhoto_Data"
    marker = b"\x00\x00\x30\x0a"
    field = marker + struct.pack("<I", len(name)) + name + video
    index = (
        b"SEFH"
        + struct.pack("<I", 106)
        + struct.pack("<I", 1)
        + marker
        + struct.pack("<I", len(field))
        + struct.pack("<I", len(field))
    )
    # Version 106 stores the bytes between SEFH and SEFT (24), not the
    # complete footer length used by newer Samsung revisions.
    return field + index + struct.pack("<I", 24) + b"SEFT"


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
    try:
        numerator, denominator = value.split("/", 1)
        result = float(numerator) / float(denominator)
        return result if result > 0 else 30.0
    except (ValueError, ZeroDivisionError):
        return 30.0


def _jpeg_end(data: bytes) -> int:
    """Return the end offset of the first complete JPEG codestream."""
    if not data.startswith(b"\xff\xd8"):
        raise ForgeError("提交文件不是有效的 JPEG 图片")
    pos = 2
    in_scan = False
    while pos < len(data):
        marker_at = data.find(b"\xff", pos)
        if marker_at < 0 or marker_at + 1 >= len(data):
            break
        marker_pos = marker_at
        while marker_pos + 1 < len(data) and data[marker_pos + 1] == 0xFF:
            marker_pos += 1
        marker = data[marker_pos + 1]
        if in_scan:
            if marker == 0x00 or 0xD0 <= marker <= 0xD7:
                pos = marker_pos + 2
                continue
            in_scan = False
        if marker == 0xD9:
            return marker_pos + 2
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos = marker_pos + 2
            continue
        if marker_pos + 4 > len(data):
            break
        segment_length = int.from_bytes(data[marker_pos + 2 : marker_pos + 4], "big")
        if segment_length < 2 or marker_pos + 2 + segment_length > len(data):
            break
        pos = marker_pos + 2 + segment_length
        if marker == 0xDA:
            in_scan = True
    raise ForgeError("JPEG 主图结构不完整")


def _mp4_end(data: bytes, start: int) -> int | None:
    pos = start
    box_types: set[bytes] = set()
    while pos + 8 <= len(data):
        size = int.from_bytes(data[pos : pos + 4], "big")
        box_type = data[pos + 4 : pos + 8]
        header_size = 8
        if size == 1:
            if pos + 16 > len(data):
                break
            size = int.from_bytes(data[pos + 8 : pos + 16], "big")
            header_size = 16
        elif size == 0:
            size = len(data) - pos
        if size < header_size or pos + size > len(data):
            break
        if not all(0x20 <= value <= 0x7E for value in box_type):
            break
        box_types.add(box_type)
        pos += size
    if {b"ftyp", b"moov", b"mdat"}.issubset(box_types):
        return pos
    return None


def _find_embedded_mp4(data: bytes, jpeg_end: int) -> tuple[int, bytes]:
    search_at = jpeg_end
    attempts = 0
    while attempts < 32:
        ftyp = data.find(b"ftyp", search_at)
        if ftyp < 4:
            break
        start = ftyp - 4
        search_at = ftyp + 4
        attempts += 1
        declared = int.from_bytes(data[start:ftyp], "big")
        if declared < 8 or declared > 1024 or start < jpeg_end:
            continue
        end = _mp4_end(data, start)
        if end is not None:
            return start, data[start:end]
    raise ForgeError("JPEG 后没有找到完整的 MP4 动态视频")


def inspect_motion_photo_submission(template: str | Path) -> SubmissionProfile:
    """Apply vendor-neutral, container-level checks to a submitted sample."""
    template = Path(template)
    if not template.is_file():
        raise ForgeError(f"提交文件不存在：{template}")
    data = template.read_bytes()
    jpeg_end = _jpeg_end(data)
    video_offset, video = _find_embedded_mp4(data, jpeg_end)
    tags = _exif_json(template, "-Make", "-Model", "-ImageWidth", "-ImageHeight")
    with tempfile.TemporaryDirectory(prefix="wechat-live-submission-") as td:
        video_path = Path(td) / "motion.mp4"
        video_path.write_bytes(video)
        probe = _ffprobe(video_path)
    format_name = str(probe.get("format", {}).get("format_name", ""))
    if not any(name in format_name.split(",") for name in ("mov", "mp4")):
        raise ForgeError("附加内容不是可识别的 MP4 视频")
    video_stream = next(
        (
            item
            for item in probe.get("streams", [])
            if item.get("codec_type") == "video"
        ),
        None,
    )
    if not video_stream:
        raise ForgeError("附加 MP4 不包含视频流")
    width = int(video_stream.get("width", 0))
    height = int(video_stream.get("height", 0))
    duration_value = video_stream.get("duration") or probe.get("format", {}).get(
        "duration"
    )
    try:
        duration = float(duration_value or 0)
    except (TypeError, ValueError):
        duration = 0
    fps = _fps(video_stream.get("avg_frame_rate"))
    try:
        frame_count = int(video_stream.get("nb_frames") or 0)
    except (TypeError, ValueError):
        frame_count = 0
    if frame_count <= 0:
        frame_count = round(duration * fps)
    if width < 64 or height < 64:
        raise ForgeError("动态视频尺寸无效")
    if duration < 0.1 or duration > 30:
        raise ForgeError("动态视频时长应在 0.1–30 秒之间")
    if frame_count < 2:
        raise ForgeError("动态视频没有足够的视频帧")
    return SubmissionProfile(
        format="generic-jpeg-mp4",
        make=str(tags.get("Make", "未知厂商")),
        model=str(tags.get("Model", "未知机型")),
        photo_width=int(tags["ImageWidth"]),
        photo_height=int(tags["ImageHeight"]),
        video_width=width,
        video_height=height,
        video_codec=str(video_stream.get("codec_name", "unknown")),
        video_duration=duration,
        video_fps=fps,
        video_length=len(video),
        video_offset=video_offset,
    )


def inspect_template(template: str | Path) -> TemplateProfile:
    template = Path(template)
    if not template.is_file():
        raise ForgeError(f"Template not found: {template}")
    data = template.read_bytes()
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
    is_oplus = (
        int(tags.get("OLivePhotoVersion", 0)) == 2
        and tags.get("MotionPhotoOwner") == "oplus"
    )
    if is_oplus:
        trailer = _extract_vendor_trailer(data)
        video_length = int(tags.get("VideoLength", 0))
        if video_length <= 0 or video_length + len(trailer) >= len(data):
            raise ForgeError("Template VideoLength is invalid")
        template_format = "oplus-v2"
        timestamp_us = int(tags.get("MotionPhotoPresentationTimestampUs", 0))
    else:
        try:
            trailer, video_length = _extract_honor_trailer(data)
        except ForgeError as exc:
            make = str(tags.get("Make", "unknown"))
            raise ForgeError(
                f"Unsupported motion-photo template format (manufacturer: {make})"
            ) from exc
        template_format = "honor-v2"
        timestamp_us = 500_000
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
        format=template_format,
        make=str(tags.get("Make", "OPPO")),
        model=str(tags.get("Model", "OPLUS device")),
        user_comment=str(
            tags.get(
                "UserComment",
                "oplus_8388640" if template_format == "oplus-v2" else "",
            )
        ),
        photo_width=int(tags["ImageWidth"]),
        photo_height=int(tags["ImageHeight"]),
        video_width=int(video_stream["width"]),
        video_height=int(video_stream["height"]),
        video_codec=str(video_stream.get("codec_name", "hevc")),
        video_duration=float(probe.get("format", {}).get("duration", 2.1)),
        video_fps=_fps(video_stream.get("avg_frame_rate")),
        presentation_timestamp_us=timestamp_us,
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


def _protocol_xmp(
    format_name: str, video_length: int, timestamp_us: int
) -> str | None:
    """Create XMP for template-free protocols backed by public specifications."""
    if format_name in {"huawei-live", "samsung-sef-v106"}:
        return None
    camera_fields = (
        f' GCamera:MicroVideo="1" GCamera:MicroVideoVersion="1"'
        f' GCamera:MicroVideoOffset="{video_length}"'
        f' GCamera:MicroVideoPresentationTimestampUs="{timestamp_us}"'
        if format_name == "microvideo-v1"
        else f' GCamera:MotionPhoto="1" GCamera:MotionPhotoVersion="1"'
        f' GCamera:MotionPhotoPresentationTimestampUs="{timestamp_us}"'
    )
    vendor_fields = ""
    if format_name == "oplus-open-v2":
        vendor_fields = (
            ' xmlns:OpCamera="http://ns.oplus.com/photos/1.0/camera/"'
            f' OpCamera:MotionPhotoPrimaryPresentationTimestampUs="{timestamp_us}"'
            ' OpCamera:MotionPhotoOwner="oplus" OpCamera:OLivePhotoVersion="2"'
            f' OpCamera:VideoLength="{video_length}"'
            ' OpCamera:MotionPhotoFeatureFlag="1"'
        )
    directory = ""
    namespaces = ""
    if format_name != "microvideo-v1":
        namespaces = (
            ' xmlns:Container="http://ns.google.com/photos/1.0/container/"'
            ' xmlns:Item="http://ns.google.com/photos/1.0/container/item/"'
        )
        padding = 24 if format_name == "samsung-sef-v106" else 0
        directory = (
            "<Container:Directory><rdf:Seq>"
            '<rdf:li rdf:parseType="Resource"><Container:Item '
            'Item:Mime="image/jpeg" Item:Semantic="Primary" Item:Length="0" '
            f'Item:Padding="{padding}"/></rdf:li>'
            '<rdf:li rdf:parseType="Resource"><Container:Item '
            'Item:Mime="video/mp4" Item:Semantic="MotionPhoto" '
            f'Item:Length="{video_length}" Item:Padding="0"/></rdf:li>'
            "</rdf:Seq></Container:Directory>"
        )
    return (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about=""'
        ' xmlns:GCamera="http://ns.google.com/photos/1.0/camera/"'
        f"{namespaces}{camera_fields}{vendor_fields}>"
        f"{directory}</rdf:Description></rdf:RDF></x:xmpmeta>"
        '<?xpacket end="w"?>'
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
    template: Path | None,
    xmp_file: Path | None,
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
    if template is not None:
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
    args = ["exiftool", "-overwrite_original"]
    if xmp_file is not None:
        args.append(f"-XMP<={xmp_file}")
    args.extend(
        [
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
    _run(args)


def _validate_oplus(
    output: Path, expected_video_length: int, trailer_length: int
) -> None:
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


def _validate_honor(output: Path, expected_video_length: int) -> None:
    data = output.read_bytes()
    trailer, video_length = _extract_honor_trailer(data)
    payload_start = len(data) - len(trailer) - video_length
    tags = _exif_json(output, "-Orientation", "-Make", "-Model")
    checks = {
        "Orientation": int(tags.get("Orientation", 0)) == 1,
        "Manufacturer": str(tags.get("Make", "")).upper() == "HONOR",
        "VideoLength": video_length == expected_video_length,
        "VideoPayload": data[payload_start + 4 : payload_start + 8] == b"ftyp",
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
    template_data = template.read_bytes()
    if profile.format == "oplus-v2":
        trailer = _extract_vendor_trailer(template_data)
    elif profile.format == "honor-v2":
        trailer, _ = _extract_honor_trailer(template_data)
    else:
        raise ForgeError(f"Unsupported template format: {profile.format}")
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
        if profile.format == "oplus-v2":
            xmp_file.write_text(
                _prepare_xmp(template, len(video_bytes), len(trailer), timestamp_us)
            )
            metadata_xmp: Path | None = xmp_file
        else:
            metadata_xmp = None
        log("[3/4] Cloning phone metadata and vendor trailer")
        _write_metadata(
            cover_jpg,
            template,
            metadata_xmp,
            metadata_jpg,
            cover_target[0],
            cover_target[1],
            profile,
        )
        jpeg = metadata_jpg.read_bytes()
        if profile.format == "oplus-v2":
            probe_mpf = _build_mpf_segment(0)
            mpf = _build_mpf_segment(len(jpeg) + len(probe_mpf))
            insert_at = _app_insertion_point(jpeg)
            output.write_bytes(
                jpeg[:insert_at] + mpf + jpeg[insert_at:] + video_bytes + trailer
            )
        else:
            trailer = _rewrite_honor_trailer(trailer, len(video_bytes))
            output.write_bytes(jpeg + video_bytes + trailer)
    log("[4/4] Validating output")
    if profile.format == "oplus-v2":
        _validate_oplus(output, len(video_bytes), len(trailer))
    else:
        _validate_honor(output, len(video_bytes))
    return BuildResult(output, profile, len(video_bytes), len(trailer), _sha256(output))


def build_motion_photo_from_profile(
    *,
    profile: TemplateProfile,
    cover: str | Path,
    video: str | Path,
    output: str | Path,
    options: BuildOptions | None = None,
    log: Log = print,
) -> BuildResult:
    """Build from a documented protocol profile without a user-supplied sample."""
    supported = {
        "microvideo-v1",
        "motionphoto-v2",
        "samsung-sef-v106",
        "oplus-open-v2",
        "huawei-live",
    }
    if profile.format not in supported:
        raise ForgeError(f"Unsupported open protocol profile: {profile.format}")
    options = options or BuildOptions()
    missing = check_dependencies()
    if missing:
        raise ForgeError("Install required commands first: " + ", ".join(missing))
    cover, video, output = map(Path, (cover, video, output))
    for path in (cover, video):
        if not path.is_file():
            raise ForgeError(f"Input not found: {path}")
    source_width, source_height = _image_dimensions(cover)
    if options.cover_rotation % 180:
        source_width, source_height = source_height, source_width
    cover_target = _target_dimensions(
        source_width, source_height, profile.photo_width, profile.photo_height
    )
    video_target = _target_dimensions(
        source_width, source_height, profile.video_width, profile.video_height
    )
    duration = options.duration if options.duration is not None else profile.video_duration
    if duration <= 0:
        raise ForgeError("Duration must be positive")
    key_time = (
        options.key_time
        if options.key_time is not None
        else profile.presentation_timestamp_us / 1_000_000
    )
    key_time = min(max(0.0, key_time), duration)
    timestamp_us = round(key_time * 1_000_000)
    output.parent.mkdir(parents=True, exist_ok=True)
    log(f"Protocol profile: {profile.make} {profile.model}")
    with tempfile.TemporaryDirectory(prefix="wechat-motion-photo-profile-") as td:
        temp = Path(td)
        cover_jpg = temp / "cover.jpg"
        video_mp4 = temp / "motion.mp4"
        metadata_jpg = temp / "metadata.jpg"
        xmp_file = temp / "profile.xmp"
        log("[1/4] Processing cover")
        _transcode_cover(cover, cover_jpg, cover_target, options)
        log("[2/4] Processing motion video")
        _transcode_video(video, video_mp4, video_target, profile, duration, options)
        video_bytes = video_mp4.read_bytes()
        xmp = _protocol_xmp(profile.format, len(video_bytes), timestamp_us)
        metadata_xmp: Path | None = None
        if xmp is not None:
            xmp_file.write_text(xmp, encoding="utf-8")
            metadata_xmp = xmp_file
        log("[3/4] Writing documented phone protocol")
        _write_metadata(
            cover_jpg,
            None,
            metadata_xmp,
            metadata_jpg,
            cover_target[0],
            cover_target[1],
            profile,
        )
        jpeg = metadata_jpg.read_bytes()
        trailer = b""
        if profile.format == "samsung-sef-v106":
            trailer = _build_samsung_sef(video_bytes)
            output.write_bytes(jpeg + trailer)
        elif profile.format == "huawei-live":
            cover_frame = round(key_time * profile.video_fps)
            total_frames = round(duration * profile.video_fps)
            trailer = _build_huawei_trailer(
                len(video_bytes), cover_frame, total_frames
            )
            output.write_bytes(jpeg + video_bytes + trailer)
        elif profile.format == "oplus-open-v2":
            probe_mpf = _build_mpf_segment(0)
            mpf = _build_mpf_segment(len(jpeg) + len(probe_mpf))
            insert_at = _app_insertion_point(jpeg)
            output.write_bytes(
                jpeg[:insert_at] + mpf + jpeg[insert_at:] + video_bytes
            )
        else:
            output.write_bytes(jpeg + video_bytes)
    log("[4/4] Validating output")
    submission = inspect_motion_photo_submission(output)
    if submission.video_length != len(video_bytes):
        raise ForgeError("Output validation failed: VideoLength")
    output_data = output.read_bytes()
    if profile.format == "samsung-sef-v106" and not output_data.endswith(b"SEFT"):
        raise ForgeError("Output validation failed: SamsungSEF")
    if profile.format == "huawei-live":
        _, actual_length = _extract_honor_trailer(output_data)
        if actual_length != len(video_bytes):
            raise ForgeError("Output validation failed: HUAWEIVideoLength")
    return BuildResult(
        output, profile, len(video_bytes), len(trailer), _sha256(output)
    )
