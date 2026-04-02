"""Library settings."""

import logging
from functools import cache
from typing import Any

# Django
from django.conf import settings as django_settings
from django.db import connection
from django.test.signals import setting_changed

# Define constants for default and fixed settings keys
FILTER_KEY = "FILTER_KEY"
AND_KEY = "AND_KEY"
OR_KEY = "OR_KEY"
NOT_KEY = "NOT_KEY"
IS_POSTGRESQL = "IS_POSTGRESQL"
HAS_TRIGRAM_EXTENSION = "HAS_TRIGRAM_EXTENSION"
AGGREGATE_MAX_VALUES = "AGGREGATE_MAX_VALUES"
AGGREGATE_MAX_UNIQUES = "AGGREGATE_MAX_UNIQUES"

# Django settings key constant
DJANGO_SETTINGS_KEY = "DJANGO_GRAPHENE_FILTERS"

# Initialize default and fixed settings
DEFAULT_SETTINGS = {
    FILTER_KEY: "filter",
    AND_KEY: "and",
    OR_KEY: "or",
    NOT_KEY: "not",
    AGGREGATE_MAX_VALUES: 10000,
    AGGREGATE_MAX_UNIQUES: 1000,
}


@cache
def get_fixed_settings() -> dict[str, bool]:
    """Return fixed settings related to the database.

    Cached after the first successful call. If the database is not
    reachable (e.g. during ``collectstatic``), falls back to safe
    defaults — full-text search features will be disabled.
    """
    try:
        is_postgresql = connection.vendor == "postgresql"
        has_trigram_extension = check_pg_trigram_extension() if is_postgresql else False
    except Exception:  # pragma: no cover — DB not reachable (e.g. collectstatic)
        logging.getLogger("django_graphene_filters").warning(
            "Could not determine database vendor — defaulting to non-PostgreSQL. "
            "Full-text search and trigram features will be disabled. "
            "This is expected during commands like collectstatic or makemigrations.",
            exc_info=True,
        )
        is_postgresql = False
        has_trigram_extension = False
    return {
        "IS_POSTGRESQL": is_postgresql,
        "HAS_TRIGRAM_EXTENSION": has_trigram_extension,
    }


def check_pg_trigram_extension() -> bool:
    """Check if the PostgreSQL trigram extension is installed."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT COUNT(*) FROM pg_extension WHERE extname='pg_trgm'")
        return cursor.fetchone()[0] == 1


FIXED_SETTINGS = get_fixed_settings()


class Settings:
    """Library settings class.

    This class manages both fixed settings that depend on the user environment
    and configurable settings that can be defined in Django's settings.py.
    """

    def __init__(self, user_settings: dict[str, Any] | None = None) -> None:
        """Initialize with optional user settings."""
        self._user_settings = user_settings

    @property
    def user_settings(self) -> dict:
        """Retrieve user-defined settings from Django settings."""
        if self._user_settings is None:
            self._user_settings = getattr(django_settings, DJANGO_SETTINGS_KEY, {}) or {}
        return self._user_settings

    def __getattr__(self, name: str) -> str | bool:
        """Retrieve a setting's value using attribute-style access."""
        # Raise an error if the setting name is invalid
        if name not in FIXED_SETTINGS and name not in DEFAULT_SETTINGS:
            raise AttributeError(f"Invalid Graphene setting: `{name}`")

        # Return the setting value based on its type (fixed, user-defined, or default)
        if name in FIXED_SETTINGS:
            return FIXED_SETTINGS[name]
        if name in self.user_settings:
            return self.user_settings[name]

        return DEFAULT_SETTINGS[name]


# Initialize settings object
settings = Settings(None)


def reload_settings(setting: str, value: Any, **kwargs) -> None:
    """Reload settings when Django's ``setting_changed`` signal is fired.

    Also refreshes the fixed DB-detection settings (``IS_POSTGRESQL``,
    ``HAS_TRIGRAM_EXTENSION``) so that test suites swapping ``DATABASES``
    see correct values without a process restart.
    """
    global settings, FIXED_SETTINGS
    if setting == DJANGO_SETTINGS_KEY:
        settings = Settings(value)
    # Refresh DB-detection flags on any settings change (covers DATABASES swaps).
    get_fixed_settings.cache_clear()
    FIXED_SETTINGS.update(get_fixed_settings())


setting_changed.connect(reload_settings)
