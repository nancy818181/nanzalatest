"""Headless checks for the shared visual system and responsive dashboard layout."""
import unittest

import tests_setup  # noqa: F401

import desktop_common
import desktop_layout
import desktop_theme


class NanzaDesignSystemTest(unittest.TestCase):
    def test_shared_navy_gold_and_surface_palette_is_consistent(self):
        expected = ("#102A43", "#B78B45", "#F4F7FA")
        self.assertEqual((desktop_common.NAVY, desktop_common.GOLD, desktop_common.LIGHT), expected)
        self.assertEqual((desktop_theme.NAVY, desktop_theme.GOLD, desktop_theme.LIGHT), expected)
        self.assertEqual((desktop_layout.NAVY, desktop_layout.GOLD, desktop_layout.LIGHT), expected)

    def test_dashboard_cards_reflow_for_laptop_and_wide_layouts(self):
        self.assertEqual(desktop_layout.dashboard_columns(640), 2)
        self.assertEqual(desktop_layout.dashboard_columns(900), 3)
        self.assertEqual(desktop_layout.dashboard_columns(1200), 4)
        self.assertEqual(desktop_layout.dashboard_columns(1), 2)


if __name__ == "__main__":
    unittest.main()
