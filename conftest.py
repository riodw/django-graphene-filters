"""Pytest session-level configuration.

Widens ``TransactionTestCase.databases`` / ``TestCase.databases`` to cover
the extra SQLite aliases (``shard_a``, ``shard_b``) registered in
``examples/cookbook/cookbook/settings.py``.

Rationale
---------
Django 6.0's ``TestCase._remove_databases_failures`` iterates every alias
in ``django.db.connections`` during teardown to un-patch connections that
``_add_databases_failures`` had wrapped to raise ``DatabaseOperationForbidden``
on disallowed access. When ``DATABASES`` declares aliases outside the test
class's implicit ``databases = {"default"}`` set, the cleanup loop can trip
an ``AttributeError: 'function' object has no attribute 'wrapped'`` because
the shard connections were never wrapped in the first place.

Declaring ``databases = "__all__"`` at the ``TransactionTestCase`` /
``TestCase`` base level sidesteps this by including every registered alias
in the per-test allow-list. Single-DB tests still only touch ``default`` at
runtime (no behavior change); they just no longer raise on the extra
aliases during cleanup.

This is scoped to the pytest session and does not affect library runtime
behaviour; consumer projects can rely on standard Django ``databases``
semantics.
"""

from django.test import TestCase, TransactionTestCase


def pytest_configure() -> None:
    """Widen the test databases allow-list to cover every declared alias.

    Runs before test classes are instantiated, so the override is in
    place for pytest-django's collection pass.  ``"__all__"`` is
    Django's sentinel for "every alias declared in ``DATABASES``".
    """
    TransactionTestCase.databases = "__all__"
    TestCase.databases = "__all__"
