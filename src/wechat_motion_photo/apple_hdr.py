"""Encode a video frame as a source-matched HDR HEIC Live Photo still."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .apple_live import _APPLE_EXIF_APP1, _APPLE_EXIF_ID_OFFSET
from .core import ForgeError


def inspect_live_hdr_heic(path: Path) -> tuple[str, int]:
    """Return the paired asset ID and HEIC transfer characteristic."""
    import pylibheif as heif

    context = heif.HeifContext()
    context.read_from_file(str(path))
    handle = context.get_primary_image_handle()
    profile = handle.get_nclx_color_profile()
    blocks = handle.get_metadata_block_ids("Exif")
    if profile is None or not blocks:
        raise ValueError("HDR HEIC 缺少色彩或实况元数据")
    data = handle.get_metadata_block(blocks[0])
    marker = b"Apple iOS\x00\x00\x01MM"
    position = data.find(marker)
    if position < 0 or len(data) < position + 69:
        raise ValueError("HDR HEIC 缺少 Apple 内容标识")
    note = data[position:]
    count = int.from_bytes(note[20:24], "big")
    offset = int.from_bytes(note[24:28], "big")
    asset_id = note[offset : offset + count].rstrip(b"\x00").decode("ascii")
    return asset_id, profile.transfer_characteristics.value


def _external_heif_encoder() -> tuple[str, dict[str, str], list[str]] | None:
    configured = os.environ.get("MOTION_HEIF_ENCODER") or shutil.which("heif-enc")
    if configured:
        return configured, os.environ.copy(), []
    root = Path(__file__).resolve().parents[2] / ".codec" / "root"
    executable = root / "usr/bin/heif-enc"
    libraries = root / "usr/lib/x86_64-linux-gnu"
    plugins = libraries / "libheif/plugins"
    if not executable.is_file() or not libraries.is_dir() or not plugins.is_dir():
        return None
    environment = os.environ.copy()
    environment["LD_LIBRARY_PATH"] = str(libraries) + ":" + environment.get("LD_LIBRARY_PATH", "")
    return str(executable), environment, ["--plugin-directory", str(plugins)]


def _write_with_external_encoder(
    video: Path, output: Path, still_time: float, transfer: str, full_range: bool,
    asset_id: str,
) -> None:
    available = _external_heif_encoder()
    if available is None:
        raise ForgeError("当前 HEIC 编码器不支持 10 位；请安装支持 10 位 x265 的 heif-enc")
    executable, environment, plugin_args = available
    png = output.with_suffix(".hdr.png")
    base = output.with_suffix(".base.heic")
    try:
        frame = subprocess.run([
            "ffmpeg", "-y", "-v", "error", "-i", str(video), "-ss", f"{still_time:.6f}",
            "-map", "0:v:0", "-frames:v", "1", "-an", "-sn", "-pix_fmt", "rgb48be",
            str(png),
        ], capture_output=True, text=True, check=False)
        if frame.returncode or not png.is_file():
            raise ForgeError("无法提取 16 位 HDR 封面帧：" + (frame.stderr.strip() or "视频帧不可用"))
        encoded = subprocess.run([
            executable, *plugin_args, "-b", "10", "-q", "95", "--colour_primaries", "9",
            "--transfer_characteristic", "18" if transfer == "arib-std-b67" else "16",
            "--matrix_coefficients", "9", "--full_range_flag", "1" if full_range else "0",
            "-o", str(base), str(png),
        ], env=environment, capture_output=True, text=True, check=False)
        if encoded.returncode or not base.is_file():
            raise ForgeError("10 位 HEIC 编码失败：" + (encoded.stderr.strip() or "编码器不可用"))
        template = Path(__file__).parent / "assets" / "apple-maker-template.heic"
        if not template.is_file():
            raise ForgeError("Apple 实况元数据模板缺失")
        shutil.copyfile(base, output)
        for args in (
            ["-TagsFromFile", str(template), "-EXIF:all"],
            [f"-Apple:ContentIdentifier={asset_id}"],
        ):
            stamped = subprocess.run(
                ["exiftool", "-overwrite_original", *args, str(output)],
                capture_output=True, text=True, check=False,
            )
            if stamped.returncode:
                raise ForgeError("无法写入 Apple 实况标识：" + stamped.stderr.strip())
    finally:
        png.unlink(missing_ok=True)
        base.unlink(missing_ok=True)


def write_live_hdr_heic(video: Path, output: Path, asset_id: str, still_time: float) -> None:
    """Copy HLG/PQ frame values into a 10-bit HEIC without tone mapping."""
    try:
        import numpy as np
        import pylibheif as heif
    except ImportError as exc:
        raise ForgeError("HDR 实况封面需要 pylibheif 和 numpy") from exc

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams", "-of", "json", str(video)],
        capture_output=True, text=True, check=False,
    )
    if probe.returncode:
        raise ForgeError("无法读取 HDR 视频色彩信息")
    try:
        stream = json.loads(probe.stdout)["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        rotation = next((int(item["rotation"]) for item in stream.get("side_data_list", []) if "rotation" in item), 0)
        if rotation % 180:
            width, height = height, width
        transfer = stream["color_transfer"]
        primaries = stream["color_primaries"]
        matrix = stream["color_space"]
        full_range = stream.get("color_range") == "pc"
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ForgeError("HDR 视频缺少有效的色彩信息") from exc
    if width % 2 or height % 2 or width <= 0 or height <= 0:
        raise ForgeError("HDR 实况封面需要偶数宽高的视频")
    if primaries != "bt2020" or transfer not in {"arib-std-b67", "smpte2084"} or matrix != "bt2020nc":
        raise ForgeError("当前仅支持 BT.2020 HLG/PQ 视频的 HDR 实况封面")

    raw_path = output.with_suffix(".p010")
    command = [
        "ffmpeg", "-y", "-v", "error", "-i", str(video), "-ss", f"{still_time:.6f}",
        "-map", "0:v:0", "-frames:v", "1", "-an", "-sn", "-pix_fmt", "p010le",
        "-f", "rawvideo", str(raw_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode or not raw_path.is_file():
        raise ForgeError("无法从 HDR 视频提取封面首帧：" + (result.stderr.strip() or "视频帧不可用"))
    try:
        pixels = np.fromfile(raw_path, dtype="<u2")
        if pixels.size != width * height * 3 // 2:
            raise ForgeError("HDR 首帧尺寸与视频元数据不一致")
        y = pixels[: width * height].reshape(height, width) >> 6
        uv = pixels[width * height :].reshape(height // 2, width // 2, 2) >> 6
        image = heif.HeifImage(width, height, heif.HeifColorspace.YCbCr, heif.HeifChroma.C420)
        for channel, values in (
            (heif.HeifChannel.Y, y),
            (heif.HeifChannel.Cb, uv[:, :, 0]),
            (heif.HeifChannel.Cr, uv[:, :, 1]),
        ):
            plane_height, plane_width = values.shape
            image.add_plane(channel, plane_width, plane_height, 10)
            image.get_plane(channel, True)[:plane_height, :plane_width] = values
        profile = heif.HeifColorProfileNclx(
            heif.HeifColorPrimaries.ITU_R_BT_2020_2_and_2100_0,
            heif.HeifTransferCharacteristics.ITU_R_BT_2100_0_HLG
            if transfer == "arib-std-b67" else heif.HeifTransferCharacteristics.ITU_R_BT_2100_0_PQ,
            heif.HeifMatrixCoefficients.ITU_R_BT_2020_2_non_constant_luminance,
            full_range,
        )
        image.set_nclx_color_profile(profile)
        exif = bytearray(_APPLE_EXIF_APP1)
        exif[58:62] = width.to_bytes(4, "big")
        exif[70:74] = height.to_bytes(4, "big")
        exif[_APPLE_EXIF_ID_OFFSET : _APPLE_EXIF_ID_OFFSET + 36] = asset_id.encode("ascii")
        try:
            encoder = heif.HeifEncoder(heif.HeifCompressionFormat.HEVC)
            encoder.set_lossy_quality(95)
            context = heif.HeifContext()
            handle = encoder.encode_image(context, image)
            context.add_exif_metadata(handle, bytes(exif[4:]))
            context.write_to_file(str(output))
        except heif.HeifError as exc:
            if "Unsupported bit depth" not in str(exc):
                raise
            _write_with_external_encoder(video, output, still_time, transfer, full_range, asset_id)
        if not output.is_file() or output.stat().st_size == 0:
            raise ForgeError("HDR HEIC 封面写入失败")
    except (OSError, ValueError, heif.HeifError) as exc:
        raise ForgeError(f"HDR HEIC 封面生成失败：{exc}") from exc
    finally:
        raw_path.unlink(missing_ok=True)
