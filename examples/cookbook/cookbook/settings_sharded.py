"""Sharded-mode Django settings for the cookbook example.

Inherits from ``settings.py`` and adds two extra SQLite aliases
(``shard_a`` / ``shard_b``) so the multi-DB / sharding test suite
(``tests/test_db_sharding.py``) can exercise the alias-propagation paths
documented in ``docs/spec-db_sharding.md``.

Usage
-----
Single-DB mode (default \u2014 ``db.sqlite3`` only):

    uv run pytest

Sharded mode (adds ``db_shard_a.sqlite3`` + ``db_shard_b.sqlite3``):

    uv run pytest --ds=examples.cookbook.cookbook.settings_sharded

Both runs cover the full suite; the sharded run additionally activates
``tests/test_db_sharding.py`` (skipped otherwise).  Consumer projects do
not need to mirror this layout \u2014 the library honours whatever alias the
caller queryset carries via ``queryset.db``.
"""

from .settings import *  # noqa: F401, F403
from .settings import BASE_DIR, DATABASES

DATABASES = {
    **DATABASES,
    "shard_a": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_shard_a.sqlite3",
    },
    "shard_b": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db_shard_b.sqlite3",
    },
}
