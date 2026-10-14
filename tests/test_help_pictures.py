"""2.9.116: the help with pictures - a page for every screen, its picture, and the Help button."""
import re
import sys
import unittest
from pathlib import Path

from tests import REPO as HERE  # 2.9.117: the program is in nanza/..., the tests in tests/
sys.path.insert(0, str(HERE / "tools"))


class HelpPicturesTest(unittest.TestCase):
    def test_every_topic_has_its_picture_and_steps_in_both_languages(self):
        from help_topics import TOPICS, WIZARD
        page = (HERE / "Assets" / "help" / "help.html").read_text(encoding="utf-8")
        for key, title_en, title_ar, _ie, _ia, steps in [*TOPICS, WIZARD]:
            self.assertIn(f'id="{key}"', page, key)
            self.assertTrue((HERE / "Assets" / "help" / "img" / f"{key}.png").exists(), key)
            self.assertTrue(steps and all(en and re.search(r"[؀-ۿ]", ar) for _t, en, ar in steps), key)

    def test_every_main_screen_has_a_topic(self):
        from help_topics import TOPICS
        import icons
        self.assertEqual({t[0] for t in TOPICS}, set(icons.PAGE_ICONS))

    def test_help_is_shipped_with_the_program(self):
        workflow = (HERE / ".github" / "workflows" / "build-windows-installer.yml").read_text(encoding="utf-8")
        self.assertIn('--add-data "Assets/help;assets/help"', workflow)
        self.assertIn("python tools/make_help.py", workflow)
        self.assertIn("def open_page_help", (HERE / "desktop.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
