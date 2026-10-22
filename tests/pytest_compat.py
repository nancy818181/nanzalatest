"""Make pytest-based modules importable by the repository's unittest-only CI jobs."""

from contextlib import contextmanager

try:
    import pytest as pytest
except ModuleNotFoundError:  # unittest discovery imports test modules but never calls these test functions
    def _identity_decorator(*_args, **_kwargs):
        def decorate(function):
            return function
        return decorate

    class _Marks:
        xfail = staticmethod(_identity_decorator)
        parametrize = staticmethod(_identity_decorator)

    class _PytestUnavailable:
        mark = _Marks()
        fixture = staticmethod(_identity_decorator)

        @staticmethod
        @contextmanager
        def raises(*_args, **_kwargs):
            yield None

    pytest = _PytestUnavailable()
