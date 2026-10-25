"""Payroll employee-list layout defaults; no Tk window or company data is used."""
import unittest

import tests_setup  # noqa: F401
from desktop_payroll import employee_visible_columns


class EmployeeColumnLayoutTest(unittest.TestCase):
    def setUp(self):
        self.columns=("number","name","job","start","leaving","branch","currency","salary","nssf","active")

    def test_default_keeps_primary_fields_and_hides_optional_details(self):
        self.assertEqual(
            employee_visible_columns(self.columns),
            ("number","name","job","start","salary","active"),
        )

    def test_saved_preferences_can_restore_every_optional_detail(self):
        self.assertEqual(employee_visible_columns(self.columns,()),self.columns)

    def test_saved_preference_hides_only_the_selected_detail(self):
        self.assertEqual(
            employee_visible_columns(self.columns,("nssf",)),
            ("number","name","job","start","leaving","branch","currency","salary","active"),
        )


if __name__ == "__main__":
    unittest.main()
