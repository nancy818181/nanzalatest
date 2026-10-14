"""Shared set-up of the tests (2.9.74). A new installation starts with no company; the tests that were written for
the older start-up (one company kept in the main file, fiscal year 2024) ask for a made-up sample company instead.
Not part of the program: only the test files import it."""
import os

os.environ.setdefault("SABER_FIRST_COMPANY", "Sample Company SARL|2024")
