# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--next-version-placeholder-->

## [0.4.0] - 2026-03-25

### Added

- **Cascade permissions** — `apply_cascade_permissions()` utility filters out
  rows whose FK targets are hidden by the target node's `get_queryset`. Use
  inside a node's `get_queryset` to enforce cascading visibility across
  relationships. Supports an optional `fields` parameter to limit which FKs
  are cascaded.
- **Sentinel nodes** — `AdvancedDjangoObjectType.get_node()` now returns a
  redacted sentinel instance (`pk=0`) instead of `None` when `get_queryset`
  hides a row. This prevents `"Cannot return null for non-nullable field"`
  GraphQL errors on non-nullable FK fields. Sentinels preserve real FK IDs
  so visible downstream targets resolve normally.
- **`isRedacted` field** — every `AdvancedDjangoObjectType` exposes an
  `isRedacted: Boolean!` computed field. Returns `true` for sentinel nodes
  (`pk=0`), `false` for real rows. Clients can query it to detect redacted
  FK targets without decoding Relay global IDs.
- **Relay Node interface warning** — `AdvancedDjangoObjectType` emits a
  `UserWarning` at class creation if the subclass does not implement the
  Relay `Node` interface, since sentinel and cascade behaviour requires
  `get_node` for FK resolution.
- **Async-safe cycle detection** — cascade permission cycle detection uses
  `contextvars.ContextVar` instead of `threading.local`, ensuring correct
  isolation under both WSGI (sync) and ASGI (async) Django.
- **Permission combination test** — `test_permissions_combos.py` exercises
  all 16 combinations of the 4 model-level view permissions (2^4) with a
  recursive response-shape validator that adapts to any query depth.
- **Async isolation test** — `test_permissions_async.py` verifies that
  concurrent coroutines on the same thread get isolated cycle-detection
  sets.

### Fixed

- **`_make_sentinel` FK detection** — used `hasattr(f, "related_model")`
  which returns `True` for ALL fields in Django 6.0.3+ (the attribute
  exists but is `None` on non-FK fields). This caused the sentinel to copy
  ALL columns from the hidden row, defeating redaction. Fixed to
  `getattr(f, "related_model", None) is not None`.
- **`apply_cascade_permissions` FK detection** — same `related_model` fix.
- **`check_pg_trigram_extension`** — queried `pg_available_extensions`
  (available but not necessarily installed) instead of `pg_extension`
  (actually installed).
- **`get_fixed_settings` crash** — database access at import time could
  crash during `collectstatic` or `makemigrations`. Now catches exceptions
  and falls back to safe defaults with a logged warning.

### Changed

- **`AnnotatedFilter`** — replaced mutable instance-level `filter_counter`
  with a module-level `itertools.count()` counter. Removed the `__init__`
  override and `annotation_name` property.
- **Postgres imports guarded** — `filters.py` and `input_data_factories.py`
  wrap `django.contrib.postgres.search` imports in `try/except ImportError`
  for forward-compatibility with non-Postgres environments.
- **Code cleanup across all modules** — removed unused imports, stale
  comments, dead enums, verbose docstrings, redundant branches, and
  `len()` checks on collections. Replaced `OrderedDict` spread-rebuilds
  with `.update()`, `rstrip` with `removesuffix`, `Optional` with
  `| None`, and `any([single_item])` with direct expressions.

### Removed

- **`BasePermission`, `AllowAny`, `IsAuthenticated`** — permission classes
  that were exported but never integrated into the framework. Cascade
  permissions are handled by `apply_cascade_permissions()` instead.
- **`RelatedOrder.queryset` parameter** — accepted but never read.
  Ordering determines sort direction, not row visibility.
- **`SearchQueryType` enum** — defined but never wired into the schema.
  Documented as a TODO for future `search_type` support.
- **`docs/design-permission-classes.md`** — superseded RFC for declarative
  permission classes.

## [0.3.1] - 2026-03-18

### Fixed

- **`_expanded_filters` cache never written** — `get_filters()` checked the
  cache on every call but never populated it, so every request re-expanded all
  `RelatedFilter` trees from scratch. On single-core servers this caused
  first-request timeouts. The cache is now written after a full, non-recursive
  expansion completes. A `"related_filters" in cls.__dict__` guard prevents the
  metaclass from storing a partial result at class-creation time, before
  `related_filters` is set on the new class.

### Tests

- **`test_get_filters_cache_written_after_first_call`** — regression test that
  asserts the cache is absent before the first call, populated after it, and
  that `BaseFilterSet.get_filters()` (the expensive super call) is invoked
  exactly once regardless of how many times `get_filters()` is called
  subsequently.

## [0.3.0] - 2026-03-14

### Added

- **Search fields** — DRF-style `search_fields` on `AdvancedDjangoObjectType`
  Meta. Exposes a `search` String argument in the GraphQL schema.
  - Lookup prefixes: `^` = `istartswith`, `=` = `iexact`, `@` = `search`
    (full-text), `$` = `iregex`. Default is `icontains`.
  - Multi-term AND: space-separated terms are ANDed; fields within a single
    term are ORed.
  - Cross-relation search fields (e.g. `"object_type__name"`).
- **Orderset `fields = "__all__"`** — `AdvancedOrderSet` Meta now accepts
  `"__all__"` to auto-derive orderable fields from all concrete (column-backed)
  model fields via `get_concrete_field_names()`.
- **Explicit queryset scoping on `RelatedFilter`** — when `queryset=` is
  provided, it acts as a security boundary.
  `_apply_related_queryset_constraints()` adds an `__in` constraint to the main
  queryset so that excluded related objects can never appear in results, even
  through nested filters.
- **Auto-derive queryset** — when no explicit `queryset=` is provided on
  `RelatedFilter` or `RelatedOrder`, the queryset is automatically derived from
  the target class's `Meta.model` using `.objects.all()`.
- **`get_concrete_field_names()` utility** — consolidated
  `model._meta.get_fields()` logic into a reusable helper in `mixins.py`.
- Integration tests for search, ordering, and filtering in the cookbook example
  (`test_search.py`, `test_ordering.py`, `test_filters.py`).

### Changed

- **Migrated from Poetry to uv** — build backend switched from `poetry-core` to
  `hatchling`. All project metadata now uses PEP 621 `[project]` tables. Dev
  dependencies use `[dependency-groups]`. CI workflow updated to use
  `astral-sh/setup-uv` and `uv run` / `uv sync`.
- Example cookbook project now uses a `pyproject.toml` with `[tool.uv.sources]`
  for editable installs instead of `requirements.txt`.
- README updated with `uv` commands for install, dev setup, testing, building,
  and publishing.

## [0.2.0] - 2026-03-10

### Added

- **Ordering system** — new `AdvancedOrderSet` class declared like a filterset
  with `Meta.model` and `Meta.fields`. Generates `orderBy` arguments with
  `ASC` / `DESC` enum values.
  - **`RelatedOrder`** — traverses relationships for cross-model ordering,
    analogous to `RelatedFilter`. Supports lazy string references.
  - **`OrderArgumentsFactory`** — converts an `AdvancedOrderSet` into nested
    `InputObjectType` trees with `OrderDirection` enums.
  - **`AdvancedDjangoObjectType`** — new `DjangoObjectType` subclass that
    accepts `orderset_class` in `Meta`, making ordering declarative.
- **Permissions system** — convention-based permission checks for both filtering
  and ordering.
  - Define `check_{field_path}_permission(self, request)` on a filterset or
    orderset. Double underscores become single underscores in the method name.
  - Auto-invoked during `__init__` for every field present in the incoming
    filter / order data.
  - Delegation: for related paths, permission checks are delegated to the child
    filterset / orderset that owns the remainder of the path.
- Pre-commit hooks with Black + Ruff for automated code formatting and linting.
- Reached **100% test coverage** with comprehensive unit tests for ordering,
  permissions, and all edge cases.

### Changed

- Upgraded Ruff configuration with an extensive rule set (pycodestyle, pyflakes,
  isort, annotations, naming, comprehensions, pydocstyle/google, eradicate,
  simplify, pyupgrade).
- Separated lint and test jobs in CI pipeline.

## [0.1.0] - 2026-02-03

### Added

- **`AdvancedFilterSet`** — extends django-filter's `BaseFilterSet` with
  tree-based **AND / OR / NOT** logical composition. Filter data is a nested
  dict; each level can contain `and`, `or`, and `not` keys that are resolved
  recursively into combined `Q` objects via `QuerySetProxy`.
- **`RelatedFilter`** — cross-model (FK / reverse-FK) filtering. Declare a
  target `AdvancedFilterSet` and a `field_name`; the metaclass expands the
  target's filters into the parent filterset with prefixed ORM paths
  (e.g. `object_type__name__icontains`).
- **Lazy class resolution** — `RelatedFilter` accepts a string class name for
  circular / same-file references. Resolved at first access via
  `LazyRelatedClassMixin`.
- **`"__all__"` on `filter_fields`** — individual fields in `Meta.filter_fields`
  can be set to `"__all__"` to auto-discover every valid lookup for that model
  field.
- **Recursion protection** — `get_filters()` tracks an `_is_expanding_filters`
  flag per class to prevent infinite loops in circular relationships.
- **`AdvancedDjangoFilterConnectionField`** — drop-in replacement for
  `DjangoFilterConnectionField`. Wires filtering into a single Relay connection
  field.
  - Dual argument modes: supports both flat GraphQL arguments
    (e.g. `name_Icontains: "foo"`) and the nested `filter: { ... }` tree in the
    same query.
- **`FilterArgumentsFactory`** — converts an `AdvancedFilterSet` into nested
  `InputObjectType` trees using `anytree.Node`, with AND / OR / NOT at every
  level.
- **PostgreSQL full-text search filters** — auto-generated from `Meta.fields`
  when the database backend is PostgreSQL.
  - `SearchQueryFilter` — full-text search via `SearchVector` + `SearchQuery`.
  - `SearchRankFilter` — search result ranking via `SearchRank`.
  - `TrigramFilter` — trigram similarity / distance (requires `pg_trgm`).
  - Dedicated GraphQL input types with self-referencing AND / OR / NOT.
  - Graceful warnings for non-PostgreSQL backends or missing extensions.
- **Configuration** — `DJANGO_GRAPHENE_FILTERS` Django settings dict for
  overriding `FILTER_KEY`, `AND_KEY`, `OR_KEY`, `NOT_KEY`. Auto-detects
  `IS_POSTGRESQL` and `HAS_TRIGRAM_EXTENSION`.
- **Cookbook example app** — full working Django + Graphene project under
  `examples/cookbook/` demonstrating all features with an EAV data model
  (`ObjectType`, `Object`, `Attribute`, `Value`).
- **CI pipeline** — GitHub Actions testing across Python 3.10–3.14 × Django
  5.1 / 5.2 / 6.0 / latest with coverage uploaded to Coveralls.

[0.4.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.4.0
[0.3.1]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.3.1
[0.3.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.3.0
[0.2.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.2.0
[0.1.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.1.0
