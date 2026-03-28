# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--next-version-placeholder-->

## [0.6.0] - 2026-03-27

### Added

- **Field-level permissions** — new `AdvancedFieldSet` base class for
  resolve-time field visibility control. Consumers declare
  `check_<field>_permission(info)` methods to gate field access and
  `resolve_<field>(root, info)` methods to override field content
  (masking, computed values, role-based output).
  - **Cascade resolution order**: `check_` (gate) → `resolve_` (content
    override) → default resolver. All three compose naturally — define
    whichever you need.
  - **`FieldSetMetaclass`** — validates configuration at class creation:
    discovers `check_<field>_permission` and `resolve_<field>` methods,
    validates model field existence (via `get_concrete_field_names` from
    `mixins.py`), stores `_field_permissions`, `_field_resolvers`, and
    `_managed_fields`.
  - **`_wrap_field_resolvers`** — in `object_type.py`, automatically wraps
    graphene field resolvers with the cascade when `fields_class` is set.
    Checks both camelCase and snake_case field keys for graphene version
    safety. Logs a warning for FieldSet fields not present in the node's
    schema.
  - **Backwards compatible** — `fields` and `fields_class` coexist.
    Existing nodes without `fields_class` work identically. No middleware
    or schema-level changes required.
- **`fields_class` on `AdvancedDjangoObjectType`** — new Meta parameter
  to declare the field permission class for a node type.
- **Cookbook example** — `fieldsets.py` with `resolve_` methods for all 3
  restricted fields (`ObjectType.description`, `Object.is_private`,
  `Value.description`), demonstrating safe fallback values for non-nullable
  fields.
- **Field permission integration tests** — `test_field_permissions.py`
  verifying staff sees real values, non-staff gets safe fallbacks,
  unrestricted fields resolve normally, anonymous user behaviour.
- **Field permission unit tests** — `test_fieldset.py` covering metaclass
  discovery, check/resolve cascade, camelCase mapping, snake_case
  fallback, missing field warnings, original resolver preservation.

## [0.5.2] - 2026-03-27

### Added

- **Sub-edge advanced filtering** — reverse-relation connection fields (e.g.
  `values` on an `ObjectNode`) now use `AdvancedDjangoFilterConnectionField`
  instead of the default `DjangoFilterConnectionField` when the target type is
  an `AdvancedDjangoObjectType`. This gives sub-edges the same tree-structured
  `filter`, `orderBy`, and `search` arguments that root-level queries have.
  - Example: `allObjects { edges { node { values(filter: { attribute: { name: { exact: "Email" } } }) { edges { node { value } } } } } }`
  - Implemented via a `singledispatch` converter override in `object_type.py`
    for `ManyToOneRel`, `ManyToManyField`, and `ManyToManyRel`. Non-Advanced
    target types fall back to the original graphene-django behaviour.
  - Flat-style arguments (e.g. `attribute_Name_Icontains`) continue to work
    for backwards compatibility.
- **Sub-edge filter/order/search tests** — `SubEdgeFilterTests` in the cookbook
  example verifying tree filter, icontains, orderBy, and search on nested
  connections.
- **Converter coverage tests** — unit tests for all fallback branches in the
  converter override (unregistered type, M2M description, non-Advanced type,
  connection without filter_fields, non-connection type).

## [0.5.1] - 2026-03-27

### Added

- **Nested connection aggregates** — aggregates are now available on nested
  connections inside edges, not just root-level connections. For example,
  `allObjects { edges { node { values { aggregates { count } } } } }` returns
  per-Object Value aggregates scoped to that Object's values.
  - Aggregate field injection moved from `AdvancedDjangoFilterConnectionField`
    to `AdvancedDjangoObjectType.__init_subclass_with_meta__`, so every
    connection using a node type with `aggregate_class` gets the field.
  - Lazy resolver: nested connections compute aggregates on-the-fly from
    `root.iterable` (the scoped queryset). Root-level connections still use
    pre-computed results from `resolve_queryset` for performance.
  - `compute(local_only=True)` parameter skips `RelatedAggregate` traversal
    for nested connections (nesting is handled by the GraphQL query structure).
- **`test_nested_connection_aggregates`** — verifies per-Object Value
  aggregates match independently computed expected values.

### Changed

- Removed `_ensure_aggregate_field_on_connection` from
  `AdvancedDjangoFilterConnectionField` — superseded by node-level injection
  in `AdvancedDjangoObjectType`.

## [0.5.0] - 2026-03-27

### Added

- **Aggregate system** — new `AdvancedAggregateSet` base class for declarative
  aggregate statistics on filtered querysets, following the same pattern as
  `AdvancedFilterSet` / `AdvancedOrderSet`.
  - Declare fields and stats in `Meta.fields` (e.g.
    `{"name": ["count", "min", "max", "mode", "uniques"]}`).
  - **10 built-in stats**: `count`, `min`, `max`, `sum`, `mean`, `median`,
    `mode`, `stdev`, `variance`, `uniques`. DB-level stats use Django ORM
    `.aggregate()`; Python-level stats use the `statistics` module.
  - **Boolean stats**: `true_count`, `false_count`.
  - **Custom stats** — register arbitrary stat names via `Meta.custom_stats`
    with a GraphQL return type mapping, then implement
    `compute_<field>_<stat>(self, queryset)`. Supports external libraries
    (numpy, scipy, pyomo) without the package knowing about them.
  - **`AggregateSetMetaclass`** — validates configuration at class creation:
    field existence, category detection (text/numeric/datetime/boolean), and
    stat compatibility. Invalid combos raise `ValueError` at startup.
  - **`AggregateArgumentsFactory`** — generates typed GraphQL `ObjectType`
    classes from an `AdvancedAggregateSet`, with per-field sub-types.
  - **Selection set optimization** — `.compute()` inspects the GraphQL
    selection set and only computes stats actually requested in the query.
  - **Permission hooks** — `check_<field>_permission(request)` blocks all
    stats for a field; `check_<field>_<stat>_permission(request)` blocks a
    specific stat. Follows the existing filterset/orderset convention.
  - **Safety limits** — `AGGREGATE_MAX_VALUES` (default 10,000) caps values
    fetched for Python-level stats; `AGGREGATE_MAX_UNIQUES` (default 1,000)
    caps the uniques list. Both configurable via `DJANGO_GRAPHENE_FILTERS`
    Django settings.
- **`RelatedAggregate`** — relationship traversal for nested aggregates,
  analogous to `RelatedFilter` / `RelatedOrder`. Supports lazy string
  references for circular dependencies.
  - **Circular reference protection** — `AggregateArgumentsFactory` tracks
    which classes are currently being built and skips circular references
    at schema generation time.
  - **`get_child_queryset()` hook** — override on `AdvancedAggregateSet` to
    apply custom visibility rules (e.g. `is_private` filtering) when
    traversing relationships.
- **`ObjectTypeFactoryMixin`** — new mixin in `mixins.py` for dynamically
  creating and caching Graphene output `ObjectType` classes (parallel to
  `InputObjectTypeFactoryMixin` which handles input types).
- **`aggregate_class` on `AdvancedDjangoObjectType`** — new Meta parameter
  to declare the aggregate class for a node type. Also accepted directly
  on `AdvancedDjangoFilterConnectionField`.
- **Connection-level aggregates** — the `aggregates` field is injected onto
  the Relay connection type as a sibling to `edges` and `pageInfo`.
  Computed from the same filtered queryset, only when the query requests it.
- **Cookbook example** — `aggregates.py` with aggregate classes for all 4
  models, including `RelatedAggregate` wiring and a custom `centroid` stat
  on `ValueAggregate` that computes mean latitude/longitude.
- **Aggregate permission tests** — `test_aggregates_permissions.py` fires
  18 queries (staff + unauthenticated + 16 permission combos) validating
  that aggregate counts respect row-level visibility.
- **Aggregate stats tests** — `test_aggregates_stats.py` verifies actual
  stat values (min, max, count, mode, uniques, centroid) against
  independently computed expected values from the DB.

### Fixed

- **`Decimal` support in seed data** — `_is_safe_generator` now accepts
  `Decimal` return values, bringing in the `geo` provider (coordinate,
  latitude, longitude) and `python.pydecimal`.
- **Deterministic `is_private` for seeded data** — ObjectTypes and
  Attributes now alternate `is_private` by sorted index (even=public,
  odd=private) instead of random assignment. Objects and Values remain
  random. This gives a stable ~50/50 split across runs.
- **Landing page** — `http://localhost:8000/` now shows a dev links page
  with clickable URLs for GraphiQL, admin, seed/delete data, and
  create/delete users.

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

[0.6.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.6.0
[0.5.2]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.5.2
[0.5.1]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.5.1
[0.5.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.5.0
[0.4.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.4.0
[0.3.1]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.3.1
[0.3.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.3.0
[0.2.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.2.0
[0.1.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.1.0
