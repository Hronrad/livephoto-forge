import unittest

from wechat_motion_photo.core import (
    ForgeError,
    _app_insertion_point,
    _build_mpf_segment,
    _extract_vendor_trailer,
    _replace_required,
    _target_dimensions,
)


class CoreTests(unittest.TestCase):
    def test_extract_vendor_trailer(self):
        payload = b"vendor-data" * 4
        trailer = (len(payload) + 4).to_bytes(4, "big") + payload
        self.assertEqual(_extract_vendor_trailer(b"jpeg+mp4" + trailer), trailer)

    def test_missing_vendor_trailer(self):
        with self.assertRaises(ForgeError):
            _extract_vendor_trailer(b"plain jpeg")

    def test_target_dimensions_follow_source_orientation(self):
        self.assertEqual(_target_dimensions(16, 9, 3072, 4096), (4096, 3072))
        self.assertEqual(_target_dimensions(9, 16, 3072, 4096), (3072, 4096))

    def test_mpf_is_jpeg_app2(self):
        segment = _build_mpf_segment(1234)
        self.assertTrue(segment.startswith(b"\xff\xe2"))
        self.assertIn(b"MPF\x00", segment)

    def test_app_insertion_point(self):
        app0 = b"\xff\xe0\x00\x04ab"
        jpeg = b"\xff\xd8" + app0 + b"\xff\xdb\x00\x04cd\xff\xd9"
        self.assertEqual(_app_insertion_point(jpeg), 2 + len(app0))

    def test_required_replacement(self):
        self.assertEqual(_replace_required(r'a="\d+"', 'a="2"', 'a="1"', "a"), 'a="2"')
        with self.assertRaises(ForgeError):
            _replace_required("missing", "x", "input", "missing")


if __name__ == "__main__":
    unittest.main()
