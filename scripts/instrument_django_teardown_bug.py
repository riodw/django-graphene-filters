"""Instrument Django's `_add_databases_failures` / `_remove_databases_failures`.

Run with::

    COOKBOOK_SHARDED=1 uv run python scripts/instrument_django_teardown_bug.py

The script is a thin shim around Django's own test runner.  It monkey-patches
both class methods so each call prints:

* What was set at wrap time (per alias, per method name).
* What's at the attribute at unwrap time (with the ``_DatabaseFailure``
  predicate so we can see whether the wrap survived).
* When `_remove_databases_failures` would have crashed, it now logs the
  actual ``method`` instead of crashing.

The output points the finger at the exact (alias, name, identity) where
the wrap got replaced between setup and teardown.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure cookbook is importable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "examples" / "cookbook"))

# Force sharded mode so two aliases exist.
os.environ.setdefault("COOKBOOK_SHARDED", "1")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cookbook.settings")

import django  # noqa: E402

django.setup()

from django.db import connections  # noqa: E402
from django.test.testcases import SimpleTestCase, _DatabaseFailure  # noqa: E402

_original_add = SimpleTestCase._add_databases_failures
_original_remove = SimpleTestCase._remove_databases_failures


def _short(obj: object) -> str:
    """One-line type/id summary."""
    return f"{type(obj).__name__}@{id(obj):x}"


@classmethod
def instrumented_add(cls):
    """Wrap connections, then dump what was actually installed."""
    print(f"\n[ADD] {cls.__module__}.{cls.__qualname__} "
          f"databases={sorted(cls.databases) if cls.databases != frozenset() else '{}'}")
    _original_add.__func__(cls)
    for alias in connections:
        if alias in cls.databases:
            continue
        connection = connections[alias]
        for name, _ in cls._disallowed_connection_methods:
            method = getattr(connection, name)
            tag = "OK" if isinstance(method, _DatabaseFailure) else "*** NOT WRAPPED"
            print(f"  [ADD] {alias}.{name}: {_short(method)} {tag}")
            if isinstance(method, _DatabaseFailure):
                print(f"        .wrapped: {_short(method.wrapped)}")


@classmethod
def instrumented_remove(cls):
    """Inspect each connection method at teardown without crashing."""
    print(f"\n[REMOVE] {cls.__module__}.{cls.__qualname__} "
          f"databases={sorted(cls.databases) if cls.databases != frozenset() else '{}'}")
    for alias in connections:
        if alias in cls.databases:
            continue
        connection = connections[alias]
        print(f"  [REMOVE] connection[{alias}]: {_short(connection)}")
        for name, _ in cls._disallowed_connection_methods:
            method = getattr(connection, name)
            is_failure = isinstance(method, _DatabaseFailure)
            tag = "OK" if is_failure else "*** WOULD CRASH"
            print(f"  [REMOVE] {alias}.{name}: {_short(method)} {tag}")
            if is_failure:
                setattr(connection, name, method.wrapped)
            else:
                print(f"           repr={method!r}")
                # Best-effort restore: leave it as-is so subsequent classes
                # can still work; this matches the no-op the proposed fix
                # would do.


SimpleTestCase._add_databases_failures = instrumented_add
SimpleTestCase._remove_databases_failures = instrumented_remove


# Run Django's test runner over the failing test class only.  The first
# four passing classes set up the state; we want the trace from
# EdgeAggregateTests' lifecycle.
from django.core.management import execute_from_command_line  # noqa: E402

execute_from_command_line(
    [
        "manage.py",
        "test",
        "cookbook.recipes.tests.test_aggregates_edge_aggregates",
        "--noinput",
        "-v",
        "2",
    ]
)
