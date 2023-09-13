"""Library settings."""

from functools import lru_cache
from typing import Any, Dict, Optional, Union

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

# Django settings key constant
DJANGO_SETTINGS_KEY = "DJANGO_GRAPHENE_FILTERS"

# Initialize default and fixed settings
DEFAULT_SETTINGS = {
    FILTER_KEY: "filter",
    AND_KEY: "and",
    OR_KEY: "or",
    NOT_KEY: "not",
}


# 5 - Cache the function to avoid repeated database calls
@lru_cache(maxsize=None)
def get_fixed_settings() -> Dict[str, bool]:
    """Return fixed settings related to the database."""
    is_postgresql = connection.vendor == "postgresql"
    has_trigram_extension = check_pg_trigram_extension() if is_postgresql else False
    return {
        "IS_POSTGRESQL": is_postgresql,
        "HAS_TRIGRAM_EXTENSION": has_trigram_extension,
    }


# 6
def check_pg_trigram_extension() -> bool:
    """Check if the PostgreSQL trigram extension is available."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT COUNT(*) FROM pg_available_extensions WHERE name='pg_trgm'"
        )
        return cursor.fetchone()[0] == 1


# 4
FIXED_SETTINGS = get_fixed_settings()


# 3
class Settings:
    """Library settings class.

    This class manages both fixed settings that depend on the user environment
    and configurable settings that can be defined in Django's settings.py.
    """

    def __init__(self, user_settings: Optional[Dict[str, Any]] = None) -> None:
        """Initialize with optional user settings."""
        self._user_settings = user_settings

    @property
    def user_settings(self) -> dict:
        """Retrieve user-defined settings from Django settings."""
        if self._user_settings is None:
            self._user_settings = getattr(django_settings, DJANGO_SETTINGS_KEY, {})
        return self._user_settings

    def __getattr__(self, name: str) -> Union[str, bool]:
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


# 2
def reload_settings(setting: str, value: Any, **kwargs) -> None:
    """Reload settings when Django's `setting_changed` signal is fired."""
    global settings
    if setting == DJANGO_SETTINGS_KEY:
        settings = Settings(value)


# 1 - Connect the reload_settings function to the setting_changed signal
setting_changed.connect(reload_settings)
