from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import shutil
import socket
import tarfile
import tempfile
import threading
import uuid
import webbrowser
import zipfile
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import Annotated

import anyio
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .apple_export import build_apple_live_pair
from .core import (
    BuildOptions,
    ForgeError,
    SubmissionProfile,
    TemplateProfile,
    build_motion_photo,
    build_motion_photo_from_profile,
    check_dependencies,
    extract_first_frame,
    _hdr_colors,
    inspect_motion_photo_submission,
    inspect_template,
)

_bundled_static_dir = Path(__file__).with_name("static")
_deployment_static_dir = Path(__file__).resolve().parents[2] / ".deployment-webui"
if os.environ.get("WECHAT_LIVE_STATIC_DIR"):
    STATIC_DIR = Path(os.environ["WECHAT_LIVE_STATIC_DIR"]).expanduser().resolve()
elif (_deployment_static_dir / "index.html").is_file():
    STATIC_DIR = _deployment_static_dir
else:
    STATIC_DIR = _bundled_static_dir
TEMPLATE_DIR = Path(__file__).with_name("templates")
USER_TEMPLATE_DIR = Path(
    os.environ.get(
        "WECHAT_LIVE_TEMPLATE_DIR", str(Path(__file__).resolve().parents[2] / "template")
    )
)
APPLE_IOS_TEMPLATE_ID = "apple-live-ios-direct"
APPLE_TEMPLATE_ID = "apple-live-mac-experimental"
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 500
BUILTIN_TEMPLATES = {
    "realme-gt-neo5-240w": {
        "label": "Realme (GT Neo5 240W)",
        "path": TEMPLATE_DIR / "realme-gt-neo5-240w.jpg",
    },
    "honor-eli-an00": {
        "label": "HONOR (ELI-AN00)",
        "path": TEMPLATE_DIR / "honor-eli-an00.jpg",
    }
}


# These entries are generated from public format specifications and open-source
# implementations.  They intentionally do not contain or impersonate a user's
# original phone photo.
OPEN_PROTOCOL_PROFILES = {
    "google-pixel-2": TemplateProfile(
        "microvideo-v1", "Google", "Pixel 2", "", 4032, 3024, 1024, 768,
        "h264", 3.0, 30.0, 1_500_000, 0, 0
    ),
    "redmi-k70-ultra": TemplateProfile(
        "microvideo-v1", "Xiaomi", "Redmi K70 Ultra", "", 4096, 3072,
        1920, 1440, "hevc", 3.0, 30.0, 1_500_000, 0, 0
    ),
    "samsung-galaxy-s7": TemplateProfile(
        "samsung-sef-v106", "samsung", "SM-G930", "", 4032, 3024,
        1280, 720, "h264", 3.0, 30.0, 1_500_000, 0, 0
    ),
    "oppo-find-x7-ultra": TemplateProfile(
        "oplus-open-v2", "OPPO", "Find X7 Ultra", "Oplus_8388608",
        4096, 3072, 1440, 1080, "h264", 3.0, 30.0, 0, 0, 0
    ),
    "huawei-mate-80": TemplateProfile(
        "huawei-live", "HUAWEI", "Mate 80", "", 4096, 3072,
        1920, 1440, "hevc", 3.0, 30.0, 1_500_000, 0, 60
    ),
}

OPEN_PROTOCOL_LABELS = {
    "google-pixel-2": "Google (Pixel 2)",
    "redmi-k70-ultra": "Redmi (K70 Ultra)",
    "samsung-galaxy-s7": "Samsung (Galaxy S7)",
    "oppo-find-x7-ultra": "OPPO (Find X7 Ultra)",
    "huawei-mate-80": "HUAWEI (Mate 80)",
}

app = FastAPI(title="微信实况照片封装器", docs_url=None, redoc_url=None)


async def _save_upload(upload: UploadFile, destination: Path) -> None:
    written = 0
    with destination.open("wb") as handle:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise ForgeError(f"{upload.filename or '文件'} 超过 2 GB 限制")
            handle.write(chunk)
    await upload.close()


def _suffix(upload: UploadFile, fallback: str) -> str:
    value = Path(upload.filename or "").suffix.lower()
    return value if value and len(value) <= 10 else fallback


def _builtin_template(template_id: str) -> Path:
    item = BUILTIN_TEMPLATES.get(template_id)
    if item:
        path = Path(item["path"])
    elif template_id.startswith("user:"):
        stem = template_id.removeprefix("user:")
        if not re.fullmatch(r"[a-z0-9-]+", stem):
            raise ForgeError("请选择有效的手机模板")
        path = USER_TEMPLATE_DIR / f"{stem}.jpg"
    else:
        raise ForgeError("请选择有效的手机模板")
    if not path.is_file():
        raise ForgeError("所选手机模板不存在")
    return path


def _template_catalog() -> list[dict[str, str]]:
    items = [
        {"id": template_id, "label": str(item["label"])}
        for template_id, item in BUILTIN_TEMPLATES.items()
    ]
    items.append({"id": APPLE_IOS_TEMPLATE_ID, "label": "iOS / iPadOS · 直接导入", "source": "apple-ios"})
    items.append({"id": APPLE_TEMPLATE_ID, "label": "Apple Live Photo · Mac 中转（备用）", "source": "apple-experimental"})
    items.extend(
        {
            "id": template_id,
            "label": OPEN_PROTOCOL_LABELS[template_id],
            "source": "open-protocol",
        }
        for template_id in OPEN_PROTOCOL_PROFILES
    )
    if USER_TEMPLATE_DIR.is_dir():
        for path in sorted(USER_TEMPLATE_DIR.glob("*.jpg")):
            metadata_path = path.with_suffix(".json")
            label = path.stem.replace("-", " ")
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                label = str(metadata.get("label") or label)
            except (OSError, ValueError, TypeError):
                pass
            items.append({"id": f"user:{path.stem}", "label": label})
    return items


def _slug(value: str) -> str:
    result = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return result[:80] or f"template-{uuid.uuid4().hex[:8]}"


def _copy_archive_member(source, destination: Path, size: int) -> None:
    if size < 1 or size > MAX_UPLOAD_BYTES:
        raise ForgeError("压缩包中的图片大小不符合要求")
    written = 0
    with destination.open("wb") as handle:
        while chunk := source.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise ForgeError("解压后的图片超过 2 GB 限制")
            handle.write(chunk)


def _archive_candidates(archive: Path, work: Path) -> list[Path]:
    candidates: list[Path] = []
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if len(members) > MAX_ARCHIVE_FILES:
                raise ForgeError("压缩包内文件过多")
            for member in members:
                if member.is_dir() or Path(member.filename).suffix.lower() not in {
                    ".jpg",
                    ".jpeg",
                }:
                    continue
                destination = work / f"candidate-{len(candidates)}.jpg"
                with bundle.open(member) as source:
                    _copy_archive_member(source, destination, member.file_size)
                candidates.append(destination)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive, "r:*") as bundle:
            members = bundle.getmembers()
            if len(members) > MAX_ARCHIVE_FILES:
                raise ForgeError("压缩包内文件过多")
            for member in members:
                if not member.isfile() or Path(member.name).suffix.lower() not in {
                    ".jpg",
                    ".jpeg",
                }:
                    continue
                source = bundle.extractfile(member)
                if source is None:
                    continue
                destination = work / f"candidate-{len(candidates)}.jpg"
                with source:
                    _copy_archive_member(source, destination, member.size)
                candidates.append(destination)
    else:
        raise ForgeError("无法识别该压缩包；请使用 ZIP、TAR、TGZ、BZ2 或 XZ 格式")
    if not candidates:
        raise ForgeError("压缩包中没有找到 JPG 动态图片")
    return candidates


def _save_pending_submission(
    source: Path,
    profile: TemplateProfile | SubmissionProfile,
    original_filename: str,
) -> dict[str, str]:
    device_slug = _slug(f"{profile.make}-{profile.model}")
    submitted_at = datetime.now(timezone.utc)
    submission_id = (
        f"{device_slug}-{submitted_at.strftime('%Y%m%dT%H%M%SZ')}-"
        f"{uuid.uuid4().hex[:8]}"
    )
    pending_dir = USER_TEMPLATE_DIR / "pending"
    pending_dir.mkdir(parents=True, exist_ok=True)
    destination = pending_dir / f"{submission_id}.jpg"
    metadata_path = pending_dir / f"{submission_id}.json"
    label = f"{profile.make} {profile.model}".strip()
    try:
        shutil.copyfile(source, destination)
        metadata_path.write_text(
            json.dumps(
                {
                    "id": submission_id,
                    "label": label,
                    "format": profile.format,
                    "status": "pending_manual_processing",
                    "submitted_at": submitted_at.isoformat(),
                    "original_filename": original_filename,
                    "retention": "destroy_after_manual_template_extraction",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    except Exception:
        destination.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)
        raise
    return {
        "id": submission_id,
        "label": label,
        "status": "pending_manual_processing",
    }


async def _resolve_template(
    upload: UploadFile | None, template_id: str, work: Path
) -> Path | TemplateProfile:
    if upload and upload.filename:
        path = work / f"template{_suffix(upload, '.jpg')}"
        await _save_upload(upload, path)
        return path
    if template_id in OPEN_PROTOCOL_PROFILES:
        return OPEN_PROTOCOL_PROFILES[template_id]
    return _builtin_template(template_id)


@app.get("/api/health")
def health() -> dict[str, object]:
    missing = check_dependencies()
    return {"ok": not missing, "missing": missing}


@app.get("/api/templates")
def templates() -> dict[str, object]:
    return {"templates": _template_catalog()}


@app.post("/api/template-submissions")
async def submit_template(file: Annotated[UploadFile, File()]) -> dict[str, object]:
    work = Path(tempfile.mkdtemp(prefix="wechat-live-template-upload-"))
    try:
        upload_path = work / f"upload{_suffix(file, '.bin')}"
        await _save_upload(file, upload_path)
        if upload_path.suffix.lower() in {".jpg", ".jpeg"}:
            candidates = [upload_path]
        else:
            candidates = await anyio.to_thread.run_sync(
                _archive_candidates, upload_path, work
            )
        source: Path | None = None
        profile = None
        last_error = "没有找到可识别的动态图片"
        for candidate in candidates:
            try:
                profile = await anyio.to_thread.run_sync(
                    inspect_motion_photo_submission, candidate
                )
                source = candidate
                break
            except (ForgeError, ValueError) as exc:
                last_error = str(exc)
        if source is None or profile is None:
            raise ForgeError(f"该文件不符合动态图片要求：{last_error}")

        submission = await anyio.to_thread.run_sync(
            _save_pending_submission, source, profile, file.filename or ""
        )
        return {
            "submission": submission,
            "profile": profile.to_dict(),
        }
    except (ForgeError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.post("/api/inspect")
async def inspect(
    template: Annotated[UploadFile | None, File()] = None,
    template_id: Annotated[str, Form()] = "",
) -> dict[str, object]:
    if template_id in {APPLE_IOS_TEMPLATE_ID, APPLE_TEMPLATE_ID}:
        if template is not None:
            await template.close()
        model = "iOS / iPadOS · 直接导入" if template_id == APPLE_IOS_TEMPLATE_ID else "Live Photo · Mac 中转"
        return {"make": "Apple", "model": model, "video_codec": "source", "video_duration": 3.0, "trailer_length": 0}
    work = Path(tempfile.mkdtemp(prefix="wechat-live-inspect-"))
    try:
        target = await _resolve_template(template, template_id, work)
        profile = (
            target
            if isinstance(target, TemplateProfile)
            else await anyio.to_thread.run_sync(inspect_template, target)
        )
        return profile.to_dict()
    except (ForgeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.post("/api/convert")
async def convert(
    video: Annotated[UploadFile, File()],
    cover: Annotated[UploadFile | None, File()] = None,
    template: Annotated[UploadFile | None, File()] = None,
    template_id: Annotated[str, Form()] = "",
    start: Annotated[float, Form()] = 0.0,
    duration: Annotated[str, Form()] = "",
    key_time: Annotated[str, Form()] = "",
    crop_mode: Annotated[str, Form()] = "crop",
    cover_rotation: Annotated[int, Form()] = 0,
    video_rotation: Annotated[int, Form()] = 0,
    zip_output: Annotated[bool, Form()] = True,
) -> FileResponse:
    work = Path(tempfile.mkdtemp(prefix="wechat-live-web-"))
    try:
        if template_id in {APPLE_IOS_TEMPLATE_ID, APPLE_TEMPLATE_ID}:
            if template is not None:
                await template.close()
            video_path = work / f"video{_suffix(video, '.mp4')}"
            await _save_upload(video, video_path)
            cover_path = None
            if cover is not None and cover.filename:
                cover_path = work / f"cover{_suffix(cover, '.jpg')}"
                await _save_upload(cover, cover_path)
            elif cover is not None:
                await cover.close()
            ios_direct = template_id == APPLE_IOS_TEMPLATE_ID
            builder = partial(
                build_apple_live_pair, video=video_path, cover=cover_path, work=work,
                start=start, duration=float(duration) if duration.strip() else None,
                key_time=float(key_time) if key_time.strip() else None,
                preserve_hdr_still=ios_direct,
            )
            still, movie = await anyio.to_thread.run_sync(builder)
            filename = "apple-live-photo.pvt.zip" if ios_direct else "apple-live-photo.zip"
            download_path = work / filename
            with zipfile.ZipFile(download_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                if ios_direct:
                    package = f"{still.stem}.pvt/"
                    bundle.writestr(package, b"")
                    bundle.write(still, arcname=package + still.name)
                    bundle.write(movie, arcname=package + movie.name)
                    bundle.writestr(
                        package + "metadata.plist",
                        plistlib.dumps({"PFVideoComplementMetadataVersionKey": "1"}),
                    )
                else:
                    bundle.write(still, arcname=still.name)
                    bundle.write(movie, arcname=movie.name)
            return FileResponse(
                download_path, media_type="application/zip", filename=filename,
                background=BackgroundTask(shutil.rmtree, work, ignore_errors=True),
            )
        template_target = await _resolve_template(template, template_id, work)
        video_path = work / f"video{_suffix(video, '.mp4')}"
        output_path = work / "livephoto.jpg"
        await _save_upload(video, video_path)
        has_cover = cover is not None and bool(cover.filename)
        if has_cover:
            cover_path = work / f"cover{_suffix(cover, '.jpg')}"
            await _save_upload(cover, cover_path)
        else:
            if cover is not None:
                await cover.close()
            cover_path = work / "cover-from-video.png"
            await anyio.to_thread.run_sync(
                extract_first_frame, video_path, cover_path, start
            )
        options = BuildOptions(
            start=start,
            duration=float(duration) if duration.strip() else None,
            key_time=(
                float(key_time) if key_time.strip() else (0.0 if not has_cover else None)
            ),
            crop_mode=crop_mode,
            cover_rotation=cover_rotation,
            video_rotation=video_rotation,
            force_sdr_cover=not has_cover,
        )
        if isinstance(template_target, TemplateProfile):
            builder = partial(
                build_motion_photo_from_profile,
                profile=template_target,
                cover=cover_path,
                video=video_path,
                output=output_path,
                options=options,
                log=lambda _message: None,
            )
        else:
            builder = partial(
                build_motion_photo,
                template=template_target,
                cover=cover_path,
                video=video_path,
                output=output_path,
                options=options,
                log=lambda _message: None,
            )
        await anyio.to_thread.run_sync(builder)
        download_path = output_path
        media_type = "image/jpeg"
        standard_android = (
            isinstance(template_target, TemplateProfile)
            and template_target.format
            in {"microvideo-v1", "motionphoto-v2", "samsung-sef-v106"}
        )
        motion_filename = (
            "MVIMG_motion_MP.jpg" if standard_android else "livephoto.jpg"
        )
        filename = motion_filename
        if zip_output:
            download_path = work / "livephoto.zip"
            with zipfile.ZipFile(
                download_path, "w", compression=zipfile.ZIP_DEFLATED
            ) as bundle:
                bundle.write(output_path, arcname=motion_filename)
            media_type = "application/zip"
            filename = "livephoto.zip"
        return FileResponse(
            download_path,
            media_type=media_type,
            filename=filename,
            background=BackgroundTask(shutil.rmtree, work, ignore_errors=True),
        )
    except (ForgeError, ValueError) as exc:
        shutil.rmtree(work, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def _free_port(host: str) -> int:
    with socket.socket() as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def main() -> None:
    parser = argparse.ArgumentParser(description="启动本机微信实况照片 WebUI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    port = args.port or _free_port(args.host)
    url = f"http://{args.host}:{port}"
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"微信实况照片封装器：{url}  （按 Ctrl+C 停止）")
    uvicorn.run(app, host=args.host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
