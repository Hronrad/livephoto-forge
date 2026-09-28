import unittest
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from wechat_motion_photo.core import (
    ForgeError,
    _jpeg_end,
    inspect_motion_photo_submission,
)
from wechat_motion_photo.web import (
    BUILTIN_TEMPLATES,
    OPEN_PROTOCOL_PROFILES,
    _archive_candidates,
    _builtin_template,
    _template_catalog,
    _save_pending_submission,
)


class WebTests(unittest.TestCase):
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
            "wechat_motion_photo.web.USER_TEMPLATE_DIR", Path(td)
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
