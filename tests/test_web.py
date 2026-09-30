import asyncio
import io
import importlib.util
import plistlib
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import UploadFile
from PIL import Image

from livephoto_forge.apple_live import inspect_live_jpeg, inspect_live_mov
from livephoto_forge.apple_hdr import inspect_live_hdr_heic
from livephoto_forge.core import (
    ForgeError,
    _extract_vendor_trailer,
    _is_ultrahdr,
    _jpeg_end,
    extract_first_frame,
    inspect_motion_photo_submission,
    inspect_template,
)
from livephoto_forge.web import (
    APPLE_IOS_TEMPLATE_ID,
    APPLE_TEMPLATE_ID,
    BUILTIN_TEMPLATES,
    OPEN_PROTOCOL_PROFILES,
    _archive_candidates,
    _builtin_template,
    _template_catalog,
    _save_pending_submission,
    convert,
)


class WebTests(unittest.TestCase):
    @unittest.skipUnless(
        all(shutil.which(name) for name in ("ffmpeg", "ffprobe"))
        and importlib.util.find_spec("pylibheif") is not None
        and importlib.util.find_spec("numpy") is not None,
        "FFmpeg and HEIC HDR dependencies are required",
    )
    def test_ios_hdr_video_keeps_hdr_heic_and_mov(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "hdr.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=128x96:rate=24:duration=1", "-pix_fmt", "yuv420p10le",
                "-c:v", "libx265", "-x265-params",
                "colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc:log-level=error",
                "-color_primaries", "bt2020", "-color_trc", "arib-std-b67",
                "-colorspace", "bt2020nc", str(source),
            ], check=True, capture_output=True)
            response = asyncio.run(convert(
                video=UploadFile(file=io.BytesIO(source.read_bytes()), filename="hdr.mp4"),
                template_id=APPLE_IOS_TEMPLATE_ID, zip_output=False,
            ))
            with zipfile.ZipFile(response.path) as bundle:
                prefix = "IMG_Apple_Live.pvt/"
                self.assertIn(prefix + "IMG_Apple_Live.HEIC", bundle.namelist())
                still = root / "IMG_Apple_Live.HEIC"
                movie = root / "IMG_Apple_Live.MOV"
                still.write_bytes(bundle.read(prefix + still.name))
                movie.write_bytes(bundle.read(prefix + movie.name))
            still_id, transfer = inspect_live_hdr_heic(still)
            self.assertEqual(transfer, 18)  # BT.2100 HLG
            self.assertEqual(still_id, inspect_live_mov(movie).asset_id)
            asyncio.run(response.background())

    @unittest.skipUnless(
        all(shutil.which(name) for name in ("ffmpeg", "ffprobe")),
        "FFmpeg is required",
    )
    def test_ios_export_downloads_importable_pvt_package(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mp4"
            cover = root / "cover.png"
            Image.new("RGB", (128, 96), (235, 15, 15)).save(cover)
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=128x96:rate=24:duration=1", "-c:v", "libx264",
                str(source),
            ], check=True)
            for cover_path in (None, cover):
                response = asyncio.run(convert(
                    video=UploadFile(file=io.BytesIO(source.read_bytes()), filename="source.mp4"),
                    cover=(
                        UploadFile(file=io.BytesIO(cover_path.read_bytes()), filename="cover.png")
                        if cover_path else None
                    ),
                    template_id=APPLE_IOS_TEMPLATE_ID, zip_output=False,
                ))
                self.assertEqual(response.filename, "apple-live-photo.pvt.zip")
                with zipfile.ZipFile(response.path) as bundle:
                    self.assertIsNone(bundle.testzip())
                    prefix = "IMG_Apple_Live.pvt/"
                    self.assertEqual(set(bundle.namelist()), {
                        prefix, prefix + "IMG_Apple_Live.JPG",
                        prefix + "IMG_Apple_Live.MOV",
                        prefix + "metadata.plist",
                    })
                    manifest = plistlib.loads(bundle.read(prefix + "metadata.plist"))
                    self.assertEqual(manifest["PFVideoComplementMetadataVersionKey"], "1")
                    still = root / "IMG_Apple_Live.JPG"
                    movie = root / "IMG_Apple_Live.MOV"
                    still.write_bytes(bundle.read(prefix + still.name))
                    movie.write_bytes(bundle.read(prefix + movie.name))
                self.assertEqual(inspect_live_jpeg(still), inspect_live_mov(movie).asset_id)
                if cover_path:
                    red, green, blue = Image.open(still).getpixel((0, 0))
                    self.assertGreater(red, 200)
                    self.assertLess(green, 50)
                    self.assertLess(blue, 50)
                asyncio.run(response.background())

    @unittest.skipUnless(
        all(shutil.which(name) for name in ("ffmpeg", "ffprobe")),
        "FFmpeg is required",
    )
    def test_apple_export_downloads_matched_jpg_mov_pair(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=128x96:rate=24:duration=1", "-c:v", "libx264",
                str(source),
            ], check=True)
            response = asyncio.run(convert(
                video=UploadFile(file=io.BytesIO(source.read_bytes()), filename="source.mp4"),
                template_id=APPLE_TEMPLATE_ID, zip_output=False,
            ))
            with zipfile.ZipFile(response.path) as bundle:
                self.assertIsNone(bundle.testzip())
                self.assertEqual(set(bundle.namelist()), {"IMG_Apple_Live.JPG", "IMG_Apple_Live.MOV"})
                still = root / "IMG_Apple_Live.JPG"
                movie = root / "IMG_Apple_Live.MOV"
                still.write_bytes(bundle.read(still.name))
                movie.write_bytes(bundle.read(movie.name))
            self.assertEqual(inspect_live_jpeg(still), inspect_live_mov(movie).asset_id)
            self.assertIn(b"still-image-time", movie.read_bytes())
            asyncio.run(response.background())

    @unittest.skipUnless(
        all(shutil.which(name) for name in ("ffmpeg", "ffprobe", "exiftool", "ultrahdr_app")),
        "HDR encoding tools are required",
    )
    def test_hdr_video_without_cover_keeps_hdr_video_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "hlg.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                "testsrc2=size=128x96:rate=26:duration=1", "-pix_fmt", "yuv420p10le",
                "-c:v", "libx265", "-tag:v", "hvc1", "-x265-params",
                "colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc",
                str(source),
            ], check=True)
            response = asyncio.run(convert(
                video=UploadFile(file=io.BytesIO(source.read_bytes()), filename="hlg.mp4"),
                cover=None, template=None, template_id="realme-gt-neo5-240w",
                start=0.0, duration="", key_time="", crop_mode="crop",
                cover_rotation=0, video_rotation=0, zip_output=True,
            ))
            with zipfile.ZipFile(response.path) as bundle:
                self.assertIsNone(bundle.testzip())
                self.assertEqual(bundle.namelist(), ["livephoto.jpg"])
                photo = root / "livephoto.jpg"
                photo.write_bytes(bundle.read("livephoto.jpg"))
            asyncio.run(response.background())
            self.assertFalse(_is_ultrahdr(photo))
            data = photo.read_bytes()
            profile = inspect_template(photo)
            trailer = _extract_vendor_trailer(data)
            video = root / "motion.mp4"
            video.write_bytes(data[-len(trailer)-profile.video_length:-len(trailer)])
            probe = subprocess.check_output([
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=color_transfer,pix_fmt", "-of", "json",
                str(video),
            ])
            self.assertIn(b"arib-std-b67", probe)
            self.assertIn(b"yuv420p10le", probe)

    @unittest.skipUnless(shutil.which("ffmpeg"), "FFmpeg is required")
    def test_missing_cover_uses_lossless_frame_from_original_video(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.mkv"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc=size=80x60:rate=2:duration=1", "-c:v", "ffv1",
                    str(source),
                ],
                check=True,
            )
            frame = root / "frame.png"
            extract_first_frame(source, frame, 0.5)
            self.assertTrue(frame.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))

            def decoded_rgb(path: Path, start: float | None = None) -> bytes:
                args = ["ffmpeg", "-v", "error", "-i", str(path)]
                if start is not None:
                    args.extend(["-ss", str(start)])
                args.extend(
                    ["-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
                )
                return subprocess.check_output(args)

            self.assertEqual(decoded_rgb(frame), decoded_rgb(source, 0.5))

            with patch("livephoto_forge.web.build_motion_photo_from_profile") as build:
                def fake_build(**kwargs):
                    self.assertEqual(kwargs["cover"].suffix, ".png")
                    self.assertEqual(decoded_rgb(kwargs["cover"]), decoded_rgb(source, 0.5))
                    self.assertEqual(kwargs["options"].key_time, 0.0)
                    kwargs["output"].write_bytes(b"test-output")

                build.side_effect = fake_build
                response = asyncio.run(
                    convert(
                        video=UploadFile(
                            file=io.BytesIO(source.read_bytes()), filename="source.mkv"
                        ),
                        template_id="google-pixel-2",
                        start=0.5,
                        zip_output=False,
                    )
                )
                self.assertEqual(response.path.read_bytes(), b"test-output")
                asyncio.run(response.background())

    def test_builtin_template_is_packaged(self):
        for template_id in ("realme-gt-neo5-240w", "honor-eli-an00"):
            self.assertIn(template_id, BUILTIN_TEMPLATES)
            self.assertTrue(_builtin_template(template_id).is_file())

    def test_unknown_builtin_template_fails(self):
        with self.assertRaises(ForgeError):
            _builtin_template("unknown-device")

    def test_open_source_device_profiles_are_listed(self):
        expected = {
            "google-pixel-2",
            "redmi-k70-ultra",
            "samsung-galaxy-s7",
            "oppo-find-x7-ultra",
            "huawei-mate-80",
        }
        self.assertEqual(set(OPEN_PROTOCOL_PROFILES), expected)
        catalog = {item["id"]: item for item in _template_catalog()}
        for template_id in expected:
            self.assertEqual(catalog[template_id]["source"], "open-protocol")
            self.assertNotIn("开源协议", catalog[template_id]["label"])
        self.assertNotIn("vivo-x300", catalog)

    def test_archive_candidates_extracts_jpeg_without_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            archive = root / "template.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("nested/template.jpg", b"jpeg-data")
                bundle.writestr("../ignored.txt", b"not-an-image")
            candidates = _archive_candidates(archive, root)
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0].parent, root)
            self.assertEqual(candidates[0].read_bytes(), b"jpeg-data")

    def test_submission_preserves_original_for_manual_processing(self):
        source = _builtin_template("honor-eli-an00")
        original = source.read_bytes()
        with tempfile.TemporaryDirectory() as td, patch(
            "livephoto_forge.web.USER_TEMPLATE_DIR", Path(td)
        ):
            profile = inspect_motion_photo_submission(source)
            submission = _save_pending_submission(source, profile, "sample.jpg")
            self.assertEqual(
                submission["status"],
                "pending_manual_processing",
            )
            pending = list((Path(td) / "pending").glob("*.jpg"))
            self.assertEqual(len(pending), 1)
            self.assertEqual(pending[0].read_bytes(), original)

    def test_vendor_neutral_submission_check(self):
        source = _builtin_template("honor-eli-an00").read_bytes()
        with tempfile.TemporaryDirectory() as td:
            candidate = Path(td) / "unknown-vendor.jpg"
            candidate.write_bytes(source.replace(b"HONOR", b"VIVOO"))
            profile = inspect_motion_photo_submission(candidate)
            self.assertEqual(profile.format, "generic-jpeg-mp4")
            self.assertEqual(profile.make, "VIVOO")

    def test_static_jpeg_and_fake_ftyp_are_rejected(self):
        source = _builtin_template("honor-eli-an00").read_bytes()
        still = source[: _jpeg_end(source)]
        with tempfile.TemporaryDirectory() as td:
            still_path = Path(td) / "still.jpg"
            still_path.write_bytes(still)
            with self.assertRaises(ForgeError):
                inspect_motion_photo_submission(still_path)
            still_path.write_bytes(still + b"\x00\x00\x00\x18ftypmp42not-an-mp4")
            with self.assertRaises(ForgeError):
                inspect_motion_photo_submission(still_path)


if __name__ == "__main__":
    unittest.main()
