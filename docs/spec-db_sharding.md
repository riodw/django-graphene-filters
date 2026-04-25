# Multi-DB and sharding compatibility in `django_graphene_filters`

## Problem

The library already preserves a caller-selected DB alias through most of the
filter/order/aggregate pipeline because it keeps operating on the same inbound
queryset. The shard breakage appears only where the library originates a fresh
queryset on a model manager instead of continuing from the caller queryset.

Three current leak sites were confirmed:

- `django_graphene_filters/permissions.py:86-88` builds the cascade-visibility
  subquery from `field.related_model._default_manager.all()`. If the parent
  queryset is pinned to a non-default alias, Django can raise a cross-database
  subquery error.
- `django_graphene_filters/aggregateset.py:647-648` builds related-aggregate
  child querysets from `target_model._default_manager.filter(...)`, which has
  the same cross-database risk.
- `django_graphene_filters/object_type.py:224-268` and
  `django_graphene_filters/object_type.py:264-268` issue sentinel/existence
  probes with `Model.objects...` on the default alias, which can cause false
  negatives when the real row lives on a shard selected by `get_queryset`.

## Current state

The root connection pipeline in
`django_graphene_filters/connection_field.py:256-351` is already alias-safe as
long as the consumer returns the correct starting queryset from their node
`get_queryset`: `resolve_queryset` receives a queryset, `AdvancedFilterSet`,
`AdvancedOrderSet`, and `AdvancedAggregateSet` all keep operating on
descendants of that queryset, and aggregate execution uses `self.queryset`
throughout.

That means sharding support here should follow one narrow principle: whenever
the library has to start a new queryset on another model, it should pin that
query to the alias of the caller queryset.
### Verified-safe call sites
The following sites were walked during the audit and do **not** need changes
because they compose on top of the caller queryset and therefore inherit
its alias automatically. They are listed here so future reviewers do not
re-audit them:
- `django_graphene_filters/connection_field.py:256-357` — `resolve_queryset`
  calls `super().resolve_queryset(...)` which delegates up to graphene-django
  and ultimately calls `cls.get_queryset(manager, info)` on the node type;
  the consumer's `get_queryset` is the single authoritative place where the
  alias is chosen. Everything downstream operates on that queryset.
- `django_graphene_filters/filterset.py` — `AdvancedFilterSet.qs`, the
  `QuerySetProxy` (`wrapt.ObjectProxy`)-based AND/OR/NOT tree evaluator,
  and the search application path all compose on `self.queryset`.
- `django_graphene_filters/orderset.py` — `AdvancedOrderSet.qs`,
  `_apply_distinct_postgres`, `_apply_distinct_emulated`, and the
  window-ordering fallback all operate on `self.queryset`.
- `django_graphene_filters/aggregateset.py` — `_compute_own_fields`
  (consolidated `.aggregate(**agg_kwargs)` + per-field `_fetch_values` +
  special/custom plans) and the `acompute` async fan-out both run against
  `self.queryset`. Only `get_child_queryset` originates a fresh queryset
  and is therefore the single fix site in this file.
- `django_graphene_filters/object_type.py:84-113` —
  `_inject_aggregates_on_connection.resolve_aggregates` reads
  `iterable = root.iterable` (the connection's filtered queryset) and
  builds the aggregate set on that, so nested aggregates inherit the
  alias. The pre-built `iterable._aggregate_set` from the root
  connection was constructed with the same queryset in
  `connection_field.py:354-355`.
- `django_graphene_filters/filters.py` (`AnnotatedFilter`,
  `SearchQueryFilter`, `SearchRankFilter`, `TrigramFilter`) — all
  `qs.annotate(...)` / `qs.filter(...)` / `qs.exclude(...)` calls operate
  on the passed-in queryset. These are PostgreSQL-only features, however,
  which ties back to the `conf.py` capability-detection non-goal: on a
  multi-vendor shard layout the global `IS_POSTGRESQL` flag is stale for
  non-default shards.
- Factory-level caches (`FilterArgumentsFactory.input_object_types`,
  `OrderArgumentsFactory.input_object_types`,
  `AggregateArgumentsFactory.input_object_types`) are schema-level and
  keyed by class name (class-based naming), not by data. They are
  shard-independent by construction.
## Proposed changes

### Alias propagation rule

Adopt the rule: library-originated ORM queries use the alias of the caller
queryset (`queryset.db` / `self.queryset.db`). This keeps single-DB behavior
unchanged because the resolved alias is still `default`, while making
subqueries and sentinel probes work when the consuming project pins querysets
to shard aliases.

### `django_graphene_filters/permissions.py`

Update `apply_cascade_permissions` so the target-node visibility subquery
starts from `field.related_model._default_manager.using(queryset.db).all()`
before passing it into `target_type.get_queryset(...)`.

This keeps the outer queryset and the inner `__in` subquery on the same alias.

### `django_graphene_filters/aggregateset.py`

Update `AdvancedAggregateSet.get_child_queryset` so the target model manager
is pinned with `.using(self.queryset.db)` before the
`filter({"<fk>__in": self.queryset})` call.

This preserves the current API while ensuring related aggregate traversals
stay on the same DB as the parent aggregate queryset.

### `django_graphene_filters/object_type.py`

Thread the active alias through sentinel handling:

- Capture the alias from the queryset returned by `cls.get_queryset(...)` in
  `get_node`.
- Use that alias for the hidden-row existence probe instead of
  default-manager routing.
- Extend `_make_sentinel` with an optional `using` parameter and use that
  alias when reloading FK IDs from the hidden source row.

This makes sentinel dispatch and FK ID copying consistent with the alias the
consumer selected in `get_queryset`.
## File / line change inventory
Below is the exhaustive list of edits the change requires. Line numbers are
relative to the current tree (`master` at time of writing).
### `django_graphene_filters/permissions.py`
One edit, inside `apply_cascade_permissions`.
`django_graphene_filters/permissions.py:85-88` — rewrite the subquery
origin to inherit the caller queryset's alias.
Before:
```python path=django_graphene_filters/permissions.py start=85
# Build subquery: visible PKs of the target model.
# Use _default_manager instead of .objects to support models
# that override the default manager name.
target_qs = target_type.get_queryset(field.related_model._default_manager.all(), info)
```
After:
```python path=null start=null
# Build subquery: visible PKs of the target model, pinned to the same
# alias as the caller queryset so the outer ``__in`` stays on one DB.
target_qs = target_type.get_queryset(
    field.related_model._default_manager.using(queryset.db).all(),
    info,
)
```
### `django_graphene_filters/aggregateset.py`
One edit, inside `AdvancedAggregateSet.get_child_queryset`, plus a small
docstring update.
`django_graphene_filters/aggregateset.py:646-647` — pin the target manager
to the parent queryset's alias.
Before:
```python path=django_graphene_filters/aggregateset.py start=646
target_model = rel_agg.aggregate_class.Meta.model
qs = target_model._default_manager.filter(**{f"{rel_agg.field_name}__in": self.queryset})
```
After:
```python path=null start=null
target_model = rel_agg.aggregate_class.Meta.model
qs = target_model._default_manager.using(self.queryset.db).filter(
    **{f"{rel_agg.field_name}__in": self.queryset}
)
```
`django_graphene_filters/aggregateset.py:629-645` — extend the docstring
to note that the child queryset inherits the parent queryset's DB alias
(no API change).
### `django_graphene_filters/object_type.py`
Three edits, all on `AdvancedDjangoObjectType`.
`django_graphene_filters/object_type.py:199-232` — add a `using: str | None = None`
kwarg to `_make_sentinel` and route the FK-reload probe through it.
Before:
```python path=django_graphene_filters/object_type.py start=200
def _make_sentinel(cls, source_pk: Any = None) -> Any:
    ...
    if source_pk is not None and fk_fields:
        # Copy real FK IDs so visible downstream targets resolve normally.
        attnames = [f.attname for f in fk_fields]
        real_values = cls._meta.model.objects.filter(pk=source_pk).values(*attnames).first()
```
After:
```python path=null start=null
def _make_sentinel(cls, source_pk: Any = None, using: str | None = None) -> Any:
    ...
    if source_pk is not None and fk_fields:
        # Copy real FK IDs so visible downstream targets resolve normally.
        # ``using`` is threaded from ``get_node`` so we reload FK IDs from
        # the same alias the consumer's ``get_queryset`` selected.
        attnames = [f.attname for f in fk_fields]
        manager = cls._meta.model._default_manager
        if using is not None:
            manager = manager.using(using)
        real_values = manager.filter(pk=source_pk).values(*attnames).first()
```
Also switches `cls._meta.model.objects` to `cls._meta.model._default_manager`
for consistency with the rest of the package (custom default manager names
are already an acknowledged concern in `permissions.py:86`).
`django_graphene_filters/object_type.py:234-281` — in `get_node`, capture the
alias of the queryset returned by `cls.get_queryset(...)` and thread it
into both the existence probe and the sentinel reload.
Before:
```python path=django_graphene_filters/object_type.py start=264
queryset = cls.get_queryset(cls._meta.model.objects, info)
try:
    return queryset.get(pk=id)
except cls._meta.model.DoesNotExist:
    if cls._meta.model.objects.filter(pk=id).exists():
        ...
        return cls._make_sentinel(source_pk=id)
    return None
```
After:
```python path=null start=null
queryset = cls.get_queryset(cls._meta.model._default_manager.all(), info)
alias = queryset.db
try:
    return queryset.get(pk=id)
except cls._meta.model.DoesNotExist:
    if cls._meta.model._default_manager.using(alias).filter(pk=id).exists():
        ...
        return cls._make_sentinel(source_pk=id, using=alias)
    return None
```
Note: the seed for `cls.get_queryset(...)` changes from `cls._meta.model.objects`
to `cls._meta.model._default_manager.all()`. This is an incidental correctness
fix (consistent with `permissions.py:86-87` and `aggregateset.py:647`) and
does not widen the surface area of the shard change.
### Docstring updates
In addition to the code edits above, extend docstrings on:
- `apply_cascade_permissions` (`django_graphene_filters/permissions.py:25-51`)
  — add a `Note:` explaining that the target-node subquery inherits the
  caller queryset's DB alias via `queryset.db`.
- `AdvancedAggregateSet.get_child_queryset`
  (`django_graphene_filters/aggregateset.py:629-645`) — add a `Note:` that
  the returned queryset is pinned to `self.queryset.db`.
- `AdvancedDjangoObjectType.get_node`
  (`django_graphene_filters/object_type.py:234-281`) — note that the
  existence probe and sentinel FK reload inherit the alias selected by
  `cls.get_queryset(...)`.
- `AdvancedDjangoObjectType._make_sentinel`
  (`django_graphene_filters/object_type.py:199-232`) — document the new
  `using` kwarg.
## Implementation notes
These details keep the implementation pass tight and prevent defensive
over-engineering.
`queryset.db` semantics. Django's `QuerySet.db` property always returns a
non-`None` alias string (`DEFAULT_DB_ALIAS` — i.e. `"default"` — when no
`.using()` was applied and no router matched). The code sketches use
`.using(queryset.db)` / `.using(self.queryset.db)` unconditionally; do not
introduce `if queryset.db is not None` guards.
`.using()` is authoritative over routers. `manager.using(alias)` bypasses
`DATABASE_ROUTERS` entirely and pins the query to `alias`. This is the
intended behavior here: the library is honoring the consumer's explicit
choice, not re-running routing logic a second time.
Cross-database error surfaced today. Without these fixes Django raises
`django.core.exceptions.FieldError` or `ValueError("Subqueries aren't
allowed across different databases. Force the inner query to be
evaluated using ``list(inner_query)``.")` depending on the subquery
shape. The alias-propagation fix avoids both.
No user-facing API breaks. The only API addition is a keyword-only
`using: str | None = None` parameter on `AdvancedDjangoObjectType._make_sentinel`
(a protected method on an abstract base class). All other changes are
purely internal rewiring.
## Explicit non-goals for this change
Two shard-adjacent areas should stay out of this first pass.
`django_graphene_filters/filters.py:143-163` — `BaseRelatedFilter.get_queryset`
auto-derives `model._default_manager.all()` for related-filter form
validation. There is no caller queryset to piggyback on here; the right
fix is a dedicated alias/shard resolver hook (e.g. reading `request._db`
or a new `DJANGO_GRAPHENE_FILTERS["SHARD_RESOLVER"]`), which is a separate
design problem.
`django_graphene_filters/conf.py:103-126`, `django_graphene_filters/conf.py:136`,
`django_graphene_filters/conf.py:187-188` — `get_fixed_settings` +
`check_pg_trigram_extension` + the module-level `FIXED_SETTINGS =
get_fixed_settings()` probe the default `django.db.connection` only.
Per-alias capability detection (e.g. shard 0 on PostgreSQL, shard 1 on
MySQL) is its own design problem and not part of the immediate
cross-database subquery breakage. This limitation also affects every
PostgreSQL-only feature path: `SearchQueryFilter`, `SearchRankFilter`,
`TrigramFilter`, and the `DB_NATIVE_PERCENTILE_STATS` branch in
`aggregateset.py:574-579`. On a mixed-vendor shard layout the global
flag is wrong for non-default shards; a follow-up should introduce a
per-alias capability map and route feature dispatch through the active
queryset's alias.

## Tests
Add targeted multi-DB coverage that exercises both the new shard-aware
branches and the unchanged single-DB path.
### Proposed test coverage
- A cascade-permissions test proving that a shard-pinned parent queryset no
  longer triggers a cross-database subquery failure and that the returned
  queryset keeps the shard alias.
- A related-aggregate test proving `get_child_queryset` inherits the parent
  queryset alias.
- A `get_node` test proving the hidden-row existence probe runs on the same
  alias as `get_queryset`, returning a sentinel instead of `None` for a row
  that exists on a shard but is filtered out.
- A sentinel-copy test proving `_make_sentinel(..., using=alias)` reloads FK
  IDs from the shard-selected row rather than the default DB.
- A regression test covering the default/single-DB path so behavior remains
  unchanged for non-sharded consumers.
### Test mechanics
- **Env-var toggle with mutually-exclusive modes.** A single
  `examples/cookbook/cookbook/settings.py` consults `COOKBOOK_SHARDED`
  in the environment. Unset, `DATABASES = {"default": db.sqlite3}`
  — Django cannot see the shard files. Set to `1`,
  `DATABASES = {"default": db_shard_a.sqlite3, "shard_b": db_shard_b.sqlite3}`
  — Django cannot see `db.sqlite3`. `default` is the primary shard
  (shard A; Django requires a `default` entry); `shard_b` is the
  secondary. Day-to-day `runserver` / `pytest` stays single-DB so it
  matches consumer reality; the multi-DB suite is a second pass::

      uv run pytest                                                          # single-DB
      COOKBOOK_SHARDED=1 uv run pytest                                       # sharded

- `tests/test_db_sharding.py` declares a module-level
  `pytestmark = pytest.mark.skipif(...)` that checks for the
  `shard_a` / `shard_b` aliases in ``settings.DATABASES``. Under the
  default settings the whole module is skipped cleanly, so the
  single-DB pass stays hermetic.
- Test classes that need cross-alias access use
  `@pytest.mark.django_db(databases=MULTI_DB)` (where
  ``MULTI_DB = ["default", "shard_a", "shard_b"]``).
- Fixtures are created per-alias with
  `Model.objects.using(alias).create(...)` — the standard replication
  shortcut doesn't automatically populate non-default aliases.
- **No DB router is required** for these tests. `.using(alias)` bypasses
  routers entirely; the tests exercise the alias-propagation paths
  directly without a router in the loop. A tiny example router can
  still be added to the cookbook for end-to-end demonstration, but the
  unit/integration tests for the library should not depend on one.
- **Root `conftest.py`** widens `TransactionTestCase.databases` /
  `TestCase.databases` to `"__all__"` as a universal safety net. In
  single-DB mode this resolves to just ``{"default"}`` (no-op);
  in sharded mode it prevents a Django 6.0 teardown bug where
  ``_remove_databases_failures`` iterates every alias in
  ``django.db.connections`` and crashes on aliases that weren't
  wrapped.
- Coverage target remains 100% line + branch, per `AGENTS.md`. The new
  branches are small (one `.using(...)` per fix site) so the added
  tests above should close them without growth in `test_coverage_gaps.py`.

## SemVer classification
This change is a **patch** release (`1.0.1`) for single-DB consumers: no
public API changes, no schema changes, behavior is byte-identical when
all library-originated queries resolve to the same alias as the caller
queryset (which is always the case on single-DB setups).
It is effectively a **bug fix** for multi-DB / shard-aware consumers:
the library previously could raise a cross-database subquery error or
silently probe the wrong alias; it now stays on the consumer-selected
alias.
The only additive API surface is the keyword-only `using: str | None = None`
parameter on the protected `AdvancedDjangoObjectType._make_sentinel`
method. That does not warrant a minor-version bump.
## Documentation
Document the compatibility model in three places:
- `CHANGELOG.md` under `[Unreleased]` noting that cascade permissions, related
  aggregates, and sentinel resolution now respect the caller queryset's DB
  alias, and that `_make_sentinel` gained an optional `using` kwarg.
- `AGENTS.md` with a short note that multi-DB compatibility depends on
  consumer code returning the correctly pinned starting queryset from
  `get_queryset`, while library-originated subqueries now inherit that alias.
- This spec (`docs/spec-db_sharding.md`) captures the alias-propagation
  rule, the verified-safe call sites, and the two follow-up areas left
  out of this pass.

## Result

After this change, the package should remain transparent for single-DB
projects while becoming compatible with standard Django multi-DB and
shard-aware projects that route the root queryset themselves. The package
will not choose shards on the consumer's behalf; it will stop accidentally
escaping the shard the consumer already selected.
