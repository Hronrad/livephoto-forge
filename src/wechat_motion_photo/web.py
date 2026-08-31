from __future__ import annotations

import argparse
import shutil
import socket
import tempfile
import threading
import webbrowser
from functools import partial
from pathlib import Path
from typing import Annotated

import anyio
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from .core import (
    BuildOptions,
    ForgeError,
    build_motion_photo,
    check_dependencies,
    inspect_template,
)

STATIC_DIR = Path(__file__).with_name("static")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

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


@app.get("/api/health")
def health() -> dict[str, object]:
    missing = check_dependencies()
    return {"ok": not missing, "missing": missing}


@app.post("/api/inspect")
async def inspect(template: Annotated[UploadFile, File()]) -> dict[str, object]:
    work = Path(tempfile.mkdtemp(prefix="wechat-live-inspect-"))
    try:
        path = work / f"template{_suffix(template, '.jpg')}"
        await _save_upload(template, path)
        profile = await anyio.to_thread.run_sync(inspect_template, path)
        return profile.to_dict()
    except (ForgeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


@app.post("/api/convert")
async def convert(
    template: Annotated[UploadFile, File()],
    cover: Annotated[UploadFile, File()],
    video: Annotated[UploadFile, File()],
    start: Annotated[float, Form()] = 0.0,
    duration: Annotated[str, Form()] = "",
    key_time: Annotated[str, Form()] = "",
    crop_mode: Annotated[str, Form()] = "crop",
    cover_rotation: Annotated[int, Form()] = 0,
    video_rotation: Annotated[int, Form()] = 0,
) -> FileResponse:
    work = Path(tempfile.mkdtemp(prefix="wechat-live-web-"))
    try:
        template_path = work / f"template{_suffix(template, '.jpg')}"
        cover_path = work / f"cover{_suffix(cover, '.jpg')}"
        video_path = work / f"video{_suffix(video, '.mp4')}"
        output_path = work / "motion-photo.jpg"
        await _save_upload(template, template_path)
        await _save_upload(cover, cover_path)
        await _save_upload(video, video_path)
        options = BuildOptions(
            start=start,
            duration=float(duration) if duration.strip() else None,
            key_time=float(key_time) if key_time.strip() else None,
            crop_mode=crop_mode,
            cover_rotation=cover_rotation,
            video_rotation=video_rotation,
        )
        await anyio.to_thread.run_sync(
            partial(
                build_motion_photo,
                template=template_path,
                cover=cover_path,
                video=video_path,
                output=output_path,
                options=options,
                log=lambda _message: None,
            )
        )
        return FileResponse(
            output_path,
            media_type="image/jpeg",
            filename="motion-photo.jpg",
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
