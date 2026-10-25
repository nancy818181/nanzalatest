"""2.9.136: fit_window keeps a window inside the screen (arithmetic only, no display needed)."""
import unittest

from window_fit import fit_window


class FakeWindow:
    def __init__(self, width, height):
        self.screen_width, self.screen_height = width, height
        self.geometry_value = None
        self.minimum = None
        self.resizable_value = None

    def winfo_screenwidth(self): return self.screen_width
    def winfo_screenheight(self): return self.screen_height
    def geometry(self, value): self.geometry_value = value
    def minsize(self, width, height): self.minimum = (width, height)
    def resizable(self, width, height): self.resizable_value = (width, height)


class FitWindowTest(unittest.TestCase):
    def test_clamps_and_centers_on_1280_by_720_screen(self):
        win = FakeWindow(1280, 720)
        self.assertEqual(fit_window(win, 1050, 760, min_width=650, min_height=450), (1050, 648, 115, 36))
        self.assertEqual(win.geometry_value, "1050x648+115+36")
        self.assertEqual(win.minimum, (650, 450))
        self.assertEqual(win.resizable_value, (True, True))

    def test_uses_entire_small_screen_limit_when_requested_size_is_large(self):
        win = FakeWindow(800, 600)
        self.assertEqual(fit_window(win, 1200, 900), (720, 540, 40, 30))
        self.assertEqual(win.minimum, (560, 360))


if __name__ == "__main__":
    unittest.main()
