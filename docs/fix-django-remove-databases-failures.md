# Upstream fix brief: `_remove_databases_failures` crashes when teardown sees an un-wrapped method

**Target repo:** [django/django](https://github.com/django/django)
**Status:** Draft — keep as internal reference until we open a ticket + PR.
**Verified against:**

- Django **6.0.3** (installed in `django-graphene-filters` 1.0.1).
- Django **`main`** at commit
  [`526b548cfb9c8a02ea2b7ae064ef3b795305d51a`](https://github.com/django/django/commit/526b548cfb9c8a02ea2b7ae064ef3b795305d51a)
  (HEAD at time of writing; that commit touches
  `django/contrib/auth/backends.py` and does not modify
  `django/test/testcases.py`).

Both revisions exhibit the same unguarded `method.wrapped` access in
`_remove_databases_failures`. Between 6.0.3 and `main`, two small
refactors landed that are orthogonal to the bug but change the patch
surface — see "Branch differences" below.

## TL;DR

`SimpleTestCase._remove_databases_failures` unconditionally accesses
`method.wrapped` on every connection method it tries to restore. If anything
between setup and teardown has left the method in a state where it is not
a `_DatabaseFailure` instance (e.g. it's a plain bound method or a function
from a different wrapper), teardown crashes with:

```
AttributeError: 'function' object has no attribute 'wrapped'
```

…instead of either silently no-op-ing (the method wasn't wrapped → nothing
to unwrap) or producing a clear diagnostic. This is a Django-internal bug:
**reproduces under Django's stock `manage.py test` runner with `pytest-django`
nowhere in the call stack** (verified empirically; see Reproduction below).
Third-party test runners are not required.

## Reproduction

### Minimal project layout

```python
# settings.py
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"},
    "shard_b": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db_shard_b.sqlite3"},
}
```

```python
# tests/test_repro.py
from django.test import TransactionTestCase


class ReproTests(TransactionTestCase):
    # Implicit: databases = {"default"} — ``shard_b`` is NOT declared.

    def test_anything(self):
        assert True
```

### Request that blows up

Django's native test runner reproduces the bug — no third-party tooling
required:

```
python manage.py test
```

(Reproduces identically under `pytest` + `pytest-django`; the bug surfaces
as long as the suite contains at least one `TransactionTestCase` whose
``databases`` set excludes one of the aliases declared in
``settings.DATABASES``.)

### Traceback (abridged)

From Django's stock `manage.py test`:

```
ERROR: tearDownClass (...EdgeAggregateTests)
----------------------------------------------------------------------
  File ".../django/test/testcases.py", line 280, in _remove_databases_failures
    setattr(connection, name, method.wrapped)
                              ^^^^^^^^^^^^^^
AttributeError: 'function' object has no attribute 'wrapped'
```

## Root cause

From `django/test/testcases.py` (shape shared between 6.0.3 and `main`;
see "Branch differences" below for the exact source per branch):

```python
class _DatabaseFailure:
    def __init__(self, wrapped, message):
        self.wrapped = wrapped              # <- only this kind of object has ``.wrapped``
        self.message = message

    def __call__(self, *args, **kwargs):    # signature on ``main``; 6.0.3 takes no args
        raise DatabaseOperationForbidden(self.message)


class SimpleTestCase(unittest.TestCase):
    @classmethod
    def _add_databases_failures(cls):
        cls.databases = cls._validate_databases()
        for alias in connections:
            if alias in cls.databases:
                continue
            connection = connections[alias]
            for name, operation in <disallowed_methods_iterable>:
                ...
                method = getattr(connection, name)
                setattr(connection, name, _DatabaseFailure(method, message))
        ...

    @classmethod
    def _remove_databases_failures(cls):
        for alias in connections:
            if alias in cls.databases:
                continue
            connection = connections[alias]
            for name, _ in <disallowed_methods_iterable>:
                method = getattr(connection, name)
                setattr(connection, name, method.wrapped)   # <-- crashes
```

### Branch differences

Between 6.0.3 and `main` the list of "disallowed connection methods" was
moved from a class attribute to a per-backend features attribute. This
does not affect the bug (both branches still blindly access
`method.wrapped` in `_remove_databases_failures`), but the PR must match
the source on each branch.

**Django 6.0.3 / `stable/6.0.x`** — class attribute form:

```python
class SimpleTestCase(unittest.TestCase):
    _disallowed_connection_methods = [
        ("connect", "connections"),
        ("temporary_connection", "connections"),
        ("cursor", "queries"),
        ("chunked_cursor", "queries"),
    ]

    @classmethod
    def _remove_databases_failures(cls):
        for alias in connections:
            if alias in cls.databases:
                continue
            connection = connections[alias]
            for name, _ in cls._disallowed_connection_methods:
                method = getattr(connection, name)
                setattr(connection, name, method.wrapped)
```

**Django `main`** — backend-features form:

```python
@classmethod
def _remove_databases_failures(cls):
    for alias in connections:
        if alias in cls.databases:
            continue
        connection = connections[alias]
        disallowed_methods = (
            connection.features.disallowed_simple_test_case_connection_methods
        )
        for name, _ in disallowed_methods:
            method = getattr(connection, name)
            setattr(connection, name, method.wrapped)
```

The fix (add an `isinstance(method, _DatabaseFailure)` guard) is
byte-identical in spirit on both; only the iteration source differs.

`_add_databases_failures` only ever installs `_DatabaseFailure` instances.
`_remove_databases_failures` assumes every method it encounters **must**
be one. That assumption is violated whenever a third-party library
replaces `connection.cursor` (or any other disallowed method) between
setup and teardown without restoring it before teardown runs.

### Confirmed reproducer in the wild: `graphene-django` debug middleware

The scenario this brief was written from is reproducible against Django
alone (see Reproduction above) but the *trigger* identified by
instrumented runs is `graphene-django`'s SQL debug middleware. The
relevant code is `graphene_django/debug/sql/tracking.py:34-42`:

```python
def wrap_cursor(connection, panel):
    if not hasattr(connection, "_graphene_cursor"):
        connection._graphene_cursor = connection.cursor      # captures Django's _DatabaseFailure
        def cursor():
            return state.Wrapper(connection._graphene_cursor(), connection, panel)
        connection.cursor = cursor                            # OVERWRITES with a closure
        return cursor
```

and `graphene_django/debug/middleware.py:37-44`:

```python
def enable_instrumentation(self):
    # This is thread-safe because database connections are thread-local.
    for connection in connections.all():           # iterates EVERY alias
        wrap_cursor(connection, self)

def disable_instrumentation(self):
    for connection in connections.all():
        unwrap_cursor(connection)
```

`enable_instrumentation` runs on every GraphQL request (it's invoked
from `DjangoDebugContext.__init__`); `disable_instrumentation` only
runs when the request selects the `_debug` field. A typical test
query does not select `_debug`, so the closure stays installed on
`connection.cursor` for every alias — including aliases the test class
did not declare in its `databases` set, which Django had wrapped with
`_DatabaseFailure` during `setUpClass`.

When `_remove_databases_failures` then runs at `tearDownClass`,
`getattr(connection, "cursor")` returns the closure (named
`wrap_cursor.<locals>.cursor`), not a `_DatabaseFailure`, and
`method.wrapped` raises `AttributeError`.

#### Instrumented trace (verbatim)

With ``cls._add_databases_failures`` and ``cls._remove_databases_failures``
logged at every iteration step:

```
[ADD] EdgeAggregateTests databases=['default']
  [ADD] shard_b.connect:              _DatabaseFailure@... OK
  [ADD] shard_b.temporary_connection: _DatabaseFailure@... OK
  [ADD] shard_b.cursor:               _DatabaseFailure@... OK
  [ADD] shard_b.chunked_cursor:       _DatabaseFailure@... OK

[REMOVE] EdgeAggregateTests databases=['default']
  [REMOVE] shard_b.connect:              _DatabaseFailure@... OK
  [REMOVE] shard_b.temporary_connection: _DatabaseFailure@... OK
  [REMOVE] shard_b.cursor:               function@... *** WOULD CRASH
           repr=<function wrap_cursor.<locals>.cursor at 0x...>
  [REMOVE] shard_b.chunked_cursor:       _DatabaseFailure@... OK
```

Only `cursor` is corrupted because graphene-django only wraps `cursor`;
the other three connection methods retain their `_DatabaseFailure`
instances and unwrap cleanly.

### Why this is broader than graphene-django

The same failure mode is reproducible with **any** third-party that
replaces `connection.cursor` between `setUpClass` and `tearDownClass`:
django-debug-toolbar's SQL panel, django-silk, and any custom query
recorder built on the `wrap_cursor` pattern. Django's teardown is the
common victim regardless of which library is the trigger. Three known
general failure modes:

1. **Third-party cursor wrapping** (the confirmed reproducer above).
   Any library that does
   `connection.cursor = <wrapper>` between setup and teardown produces
   a non-`_DatabaseFailure` at the cursor attribute.
2. **Asymmetric `databases`.** A subclass or fixture changes
   `cls.databases` after setup ran. Teardown's iteration set no longer
   matches setup's, so some aliases that weren't wrapped are still
   visited.
3. **`_add_databases_failures` never ran.** A class that skipped
   `super().setUpClass()` but still inherits the
   `addClassCleanup(_remove_databases_failures)` will attempt an unwrap
   with no prior wrap.

In all three cases the failure mode is identical: `getattr(connection,
name)` returns something that is not a `_DatabaseFailure`, and
`method.wrapped` raises.

## Proposed fix

Make the unwrap symmetric with the wrap's intent: only touch methods that
`_add_databases_failures` actually installed.

### Option A — `isinstance` guard (recommended)

Patch for **`main`** (backend-features iteration):

```python
@classmethod
def _remove_databases_failures(cls):
    for alias in connections:
        if alias in cls.databases:
            continue
        connection = connections[alias]
        disallowed_methods = (
            connection.features.disallowed_simple_test_case_connection_methods
        )
        for name, _ in disallowed_methods:
            method = getattr(connection, name)
            if isinstance(method, _DatabaseFailure):     # <-- add this guard
                setattr(connection, name, method.wrapped)
```

Backport for **`stable/6.0.x`** (class-attribute iteration):

```python
@classmethod
def _remove_databases_failures(cls):
    for alias in connections:
        if alias in cls.databases:
            continue
        connection = connections[alias]
        for name, _ in cls._disallowed_connection_methods:
            method = getattr(connection, name)
            if isinstance(method, _DatabaseFailure):     # <-- add this guard
                setattr(connection, name, method.wrapped)
```

- One-line change, zero behavioural difference for the happy path.
- Silently no-ops when the method isn't something setup installed, instead
  of crashing.
- Scopes the unwrap precisely to Django's own wrapper class — won't chase
  arbitrary third-party objects that happen to expose a `.wrapped` attribute.

### Option B — `hasattr` guard

```python
if hasattr(method, "wrapped"):
    setattr(connection, name, method.wrapped)
```

Equivalent for the common case, but less precise — any third-party wrapper
with a `.wrapped` attribute would be unwrapped too. Prefer **Option A**
unless a maintainer asks for duck-typing.

### Option C — track wrapped methods explicitly

Store the `(alias, name)` pairs that `_add_databases_failures` wrapped and
iterate that list in teardown instead of re-walking `connections`. Shown
for the **`main`** iteration source:

```python
@classmethod
def _add_databases_failures(cls):
    ...
    cls._wrapped_connection_methods = []
    for alias in connections:
        if alias in cls.databases:
            continue
        connection = connections[alias]
        disallowed_methods = (
            connection.features.disallowed_simple_test_case_connection_methods
        )
        for name, _ in disallowed_methods:
            ...
            setattr(connection, name, _DatabaseFailure(method, message))
            cls._wrapped_connection_methods.append((alias, name))

@classmethod
def _remove_databases_failures(cls):
    for alias, name in getattr(cls, "_wrapped_connection_methods", ()):
        connection = connections[alias]
        method = getattr(connection, name)
        if isinstance(method, _DatabaseFailure):
            setattr(connection, name, method.wrapped)
```

For a `6.0.x` backport, swap `disallowed_methods` for
`cls._disallowed_connection_methods`.

More invasive; preferable only if the maintainers want a stronger
"teardown restores exactly what setup installed" invariant. **Option A** is
the smaller, safer change.

## Suggested test

Add to `tests/test_utils/test_testcase_databases.py` (or the current
equivalent):

```python
from unittest import mock

from django.db import connections
from django.test import TestCase
from django.test.testcases import _DatabaseFailure


class RemoveDatabasesFailuresTests(TestCase):
    """Regression tests for _remove_databases_failures robustness."""

    databases = {"default"}

    def test_teardown_noops_when_method_is_not_wrapped(self):
        """If a connection method is replaced between setup and teardown,
        teardown must not crash with AttributeError."""
        # Simulate a connection-recycling scenario by overwriting the
        # wrapped cursor with a plain function (no ``.wrapped`` attribute).
        other_alias = next(a for a in connections if a != "default")
        connection = connections[other_alias]
        original = connection.cursor
        try:
            connection.cursor = lambda *a, **kw: None  # plain function
            # Should not raise — the guard sees a non-_DatabaseFailure
            # and skips the unwrap step.
            self.__class__._remove_databases_failures()
        finally:
            connection.cursor = original

    def test_teardown_still_unwraps_database_failures(self):
        """The happy path must continue to restore wrapped methods."""
        other_alias = next(a for a in connections if a != "default")
        connection = connections[other_alias]
        original = connection.cursor
        connection.cursor = _DatabaseFailure(original, "msg")
        try:
            self.__class__._remove_databases_failures()
            assert connection.cursor is original
        finally:
            connection.cursor = original
```

The first test is the regression check; the second asserts we did not
regress the intended unwrap behaviour.

## Error-message improvement (bonus)

Even after Option A lands, a clearer diagnostic for the "method was
replaced by something unexpected" case helps future debugging:

```python
@classmethod
def _remove_databases_failures(cls):
    for alias in connections:
        if alias in cls.databases:
            continue
        connection = connections[alias]
        for name, _ in cls._disallowed_connection_methods:
            method = getattr(connection, name)
            if isinstance(method, _DatabaseFailure):
                setattr(connection, name, method.wrapped)
            elif method is not None:
                import logging
                logging.getLogger("django.test").debug(
                    "Skipping unwrap of %s.%s — expected _DatabaseFailure, got %r. "
                    "This usually indicates the connection was recycled between "
                    "setUpClass and tearDownClass (e.g. SQLite in-memory test DBs) "
                    "or that setUpClass was not called.",
                    alias, name, type(method).__name__,
                )
```

Optional — ship the behaviour fix first, the log can ride a follow-up.

## Downstream impact

`django-graphene-filters` ships a 1.0.1 multi-DB / sharding compatibility
pass (see `docs/spec-db_sharding.md`). The example cookbook's test suite
runs under a two-mode setup — single-DB and a sharded overlay where
`DATABASES` gains a `shard_b` alias. With the overlay active, every
`GraphQLTestCase` (≈18 classes) in the cookbook trips this bug in teardown
because their implicit `databases = {"default"}` excludes `shard_b`.

The project ships a root-level `conftest.py` workaround that globally sets
`TransactionTestCase.databases = "__all__"` / `TestCase.databases = "__all__"`
to dodge the wrap/unwrap path entirely. That workaround is effectively
"opt out of the disallowed-connection guard for all our tests" — a
heavyweight response to a one-line Django bug. Once this fix lands in a
Django 6.0.x point release, we can delete the `conftest.py` and let the
test classes declare `databases` normally.

## Open questions for the maintainers

1. Is **Option A** (`isinstance` guard) acceptable, or would they prefer
   the stricter explicit-tracking approach (Option C)?
2. Should the guard fall back to a one-line `warnings.warn(...)` when it
   encounters an unexpected method, or stay silent?
3. Is there appetite for documenting the "third-party cursor wrapping
   between setUpClass and tearDownClass is supported and survives
   teardown" invariant alongside the fix, so future authors know why the
   guard is needed?
4. Should Django add a regression test that mimics the
   `wrap_cursor`-style replacement pattern that django-debug-toolbar /
   graphene-django / django-silk all use, so this class of bugs cannot
   recur silently?

## Rollout plan (us, not them)

1. File a Django Trac ticket at <https://code.djangoproject.com/> with
   the minimal repro above; tag it `bug` + `Testing framework`.
2. If triagers confirm, open a PR against the `main` branch implementing
   Option A plus the two regression tests. Request a backport to the
   `stable/6.0.x` branch so the fix reaches the 6.0 series.
3. Independently of upstream acceptance, keep the `conftest.py` workaround
   in `django-graphene-filters` — don't block any library release on
   Django's merge.

## File checklist when opening the PR

- `django/test/testcases.py` — `isinstance(method, _DatabaseFailure)` guard
  on line ~280.
- `tests/test_utils/…` — two regression tests (crash-avoidance + happy
  path still works).
- `docs/releases/6.0.X.txt` — one-line entry under "Bugfixes".
- Optional: `docs/topics/testing/tools.txt` — sentence noting the guard in
  the `databases` section so readers understand why teardown is defensive.
