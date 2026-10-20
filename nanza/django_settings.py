"""Optional settings fragment, not a standalone Django project configuration."""
from pathlib import Path

LANGUAGES = [('en', 'English'), ('ar', 'العربية')]
USE_I18N = True
LOCALE_PATHS = [Path(__file__).resolve().parent / 'locale']
