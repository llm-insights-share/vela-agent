"""Vela management CLI — thin HTTP client over /api/v1."""

try:
    from version import __version__
except ImportError:
    __version__ = "1.06"
