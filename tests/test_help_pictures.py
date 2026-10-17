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

    def test_main_help_opens_illustrated_guide(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        import desktop
        app = SimpleNamespace(open_page_help=Mock())
        with patch.object(desktop, "resource_path", return_value=str(HERE / "Assets/help/help.html")):
            desktop.SaberApp.open_user_guide(app)
        app.open_page_help.assert_called_once_with()

    def test_missing_picture_help_falls_back_to_text_guide(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        import desktop
        app = SimpleNamespace(open_page_help=Mock())
        def resource(name):
            return str(HERE / ("missing-help.html" if name.endswith("help/help.html") else "Assets/user_guide.html"))
        with patch.object(desktop, "resource_path", side_effect=resource), patch("webbrowser.open") as browser:
            desktop.SaberApp.open_user_guide(app)
        app.open_page_help.assert_not_called()
        browser.assert_called_once_with((HERE / "Assets/user_guide.html").resolve().as_uri())

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
