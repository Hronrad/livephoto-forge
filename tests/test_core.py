import unittest

from wechat_motion_photo.core import (
    ForgeError,
    _app_insertion_point,
    _build_mpf_segment,
    _build_huawei_trailer,
    _build_samsung_sef,
    _extract_honor_trailer,
    _extract_vendor_trailer,
    _replace_required,
    _protocol_xmp,
    _rewrite_honor_trailer,
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

    def test_extract_honor_trailer(self):
        video = b"\x00\x00\x00\x18ftypmp42" + b"video-data"
        trailer = (
            b"v2_f51".ljust(20)
            + b"500:1200".ljust(20)
            + f"LIVE_{len(video) + 20}".encode().ljust(20)
        )
        self.assertEqual(
            _extract_honor_trailer(b"jpeg" + video + trailer),
            (trailer, len(video)),
        )

    def test_rewrite_honor_trailer(self):
        trailer = b"v2_f51".ljust(20) + b"500:1200".ljust(20) + b"LIVE_42".ljust(20)
        rewritten = _rewrite_honor_trailer(trailer, 12345)
        self.assertEqual(rewritten[:40], trailer[:40])
        self.assertEqual(rewritten[40:].rstrip(), b"LIVE_12365")

    def test_build_huawei_trailer(self):
        video = b"\x00\x00\x00\x18ftypmp42" + b"video"
        trailer = _build_huawei_trailer(len(video), 12, 90)
        self.assertEqual(len(trailer), 60)
        self.assertEqual(
            _extract_honor_trailer(b"jpeg" + video + trailer),
            (trailer, len(video)),
        )

    def test_build_legacy_samsung_sef(self):
        trailer = _build_samsung_sef(b"video")
        self.assertIn(b"MotionPhoto_Data", trailer)
        self.assertIn(b"SEFH", trailer)
        self.assertTrue(trailer.endswith(b"\x18\x00\x00\x00SEFT"))

    def test_protocol_xmp(self):
        micro = _protocol_xmp("microvideo-v1", 123, 456)
        self.assertIn('GCamera:MicroVideoOffset="123"', micro)
        standard = _protocol_xmp("motionphoto-v2", 123, 456)
        self.assertIn('Item:Semantic="MotionPhoto"', standard)
        oppo = _protocol_xmp("oplus-open-v2", 123, 456)
        self.assertIn('OpCamera:VideoLength="123"', oppo)
        self.assertIsNone(_protocol_xmp("samsung-sef-v106", 123, 456))

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
