import unittest

from wechat_motion_photo.core import ForgeError
from wechat_motion_photo.web import BUILTIN_TEMPLATES, _builtin_template


class WebTests(unittest.TestCase):
    def test_builtin_template_is_packaged(self):
        template_id = "realme-gt-neo5-240w"
        self.assertIn(template_id, BUILTIN_TEMPLATES)
        self.assertTrue(_builtin_template(template_id).is_file())

    def test_unknown_builtin_template_fails(self):
        with self.assertRaises(ForgeError):
            _builtin_template("unknown-device")


if __name__ == "__main__":
    unittest.main()
