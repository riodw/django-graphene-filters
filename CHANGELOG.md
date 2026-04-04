# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--next-version-placeholder-->

## [Prerelease] — unreleased (targeting 0.7.3)

### Fixed

- **Computed fields not inherited from mixin/base classes** — the
  `FieldSetMetaclass` discovered computed field declarations (graphene
  `UnmountedType` attributes) only from `attrs` (the current class body),
  missing declarations on parent mixins or base classes. Changed to use
  `dir(new_class)` which includes inherited attributes.
- **Pure computed fields not wrapped with permission/deny logic** —
  `_managed_fields` was `field_permissions | field_resolvers`, excluding
  computed fields that had no `resolve_*` or `check_*_permission`. Added
  `set(computed_fields)` so all computed fields get the permission wrapper
  in `_wrap_field_resolvers`.
- **`AdvancedFieldSet` docstring inaccurate** — the cascade description
  said "raises → null" but denied non-nullable fields actually return
  type-appropriate defaults (empty string, `False`, epoch, etc.). Updated
  to reflect actual behavior.
- **Hardcoded `"and"` / `"or"` / `"not"` in `AdvancedFilterSet`** — tree
  logic in `_collect_filter_fields`, `create_form`, and
  `TreeFormMixin.errors` used literal strings instead of
  `settings.AND_KEY` / `OR_KEY` / `NOT_KEY`. Projects that changed these
  keys via `DJANGO_GRAPHENE_FILTERS` settings would silently break:
  permission collection, form construction, and error aggregation would
  not see nested trees. Now uses the configurable settings throughout.
- **`find_filter` silently returns `None`** — when no matching filter was
  found, execution fell off the end of the method returning `None`. The
  caller in `get_queryset_proxy_for_form` would then raise an unhelpful
  `AttributeError: 'NoneType' object has no attribute 'filter'`. Now
  raises `KeyError` with a descriptive message listing available filters.
- **`expand_auto_filter` swallows all exceptions** — the bare
  `except Exception: pass` hid real bugs during auto-filter expansion.
  Narrowed to `except (TypeError, KeyError)` which covers the documented
  cases (field doesn't exist on model, field name not in generated filters).
- **Search docstring claims quoted-phrase handling** — the comment said
  "handle multiple terms (quoted and non-quoted)" but `str.split()` does
  not parse quotes. Updated docstring to accurately describe behaviour:
  whitespace-split, ANDed terms, no quoted-phrase support.
- **Hardcoded `"and"` / `"or"` / `"not"` in `tree_input_type_to_data`** —
  same configuration bug as `filterset.py`: tree conversion used literal
  strings instead of `settings.AND_KEY` / `OR_KEY` / `NOT_KEY`. Now uses
  the configurable settings, aligned with all other tree-parsing code.
- **`create_search_query` NOT handling broken** —
  `SearchQueryInputType.not` is declared as `List(SearchQueryInputType)`
  in the GraphQL schema, but `create_search_query` treated it as a single
  value (no loop). Passing multiple NOT entries from GraphQL would crash.
  Now iterates the list and combines with `~` (inversion), matching the
  AND/OR pattern. Also handles `None` gracefully with `or []` fallback.
- **`OrderArgumentsFactory` infinite recursion on circular `RelatedOrder`** —
  `create_order_input_type` had no cycle guard, so circular ordersets
  (e.g. `ObjectOrder → ValueOrder → ObjectOrder`) would recurse until
  stack overflow. Added a `_building` set with try/finally, matching the
  pattern already used by `AggregateArgumentsFactory`.
- **`OrderArgumentsFactory` uses `capitalize()` instead of `pascalcase()`**
  — for snake_case relation names like `object_type`, `capitalize()`
  produced `Object_type` instead of `ObjectType`. Changed to
  `stringcase.pascalcase()` for consistency with `FilterArgumentsFactory`.
- **`FilterArgumentsFactory.arguments` defeats caching** — the
  `.arguments` property used `dict.get(key, expensive_default())` which
  evaluates `create_filter_input_type(filterset_to_trees(...))` on every
  access even when the type is already cached. Changed to an explicit
  `if key not in cache` check. The collision warning (same type name,
  different filterset) was moved from `create_filter_input_type` to
  `.arguments` so it fires on cache hits too.

## [0.7.2] - 2026-04-02

### Fixed

- **Nullable FK rows dropped by `apply_cascade_permissions`** —
  `queryset.filter(field__in=target_qs)` excluded rows where the FK is
  `NULL`, because `NULL IN (...)` evaluates to `FALSE` in SQL. Rows with
  no FK reference should remain visible. Fixed by adding
  `| Q(field__isnull=True)` to preserve nullable FK rows.
- **`apply_cascade_permissions` assumes `.objects` manager** —
  `field.related_model.objects` fails if a model overrides the default
  manager name. Changed to `field.related_model._default_manager.all()`
  which respects custom manager configuration.
- **Misleading comment in `apply_cascade_permissions`** — the comment said
  "concrete FK fields" but didn't explain why M2M is excluded. Updated to
  explicitly state "single-column FK / OneToOneField" and note that
  `ManyToManyField` lacks a `column` attribute.
- **Import-time crash on non-PostgreSQL environments** — `TrigramFilter.Value`
  used a PEP 604 union annotation `TrigramSimilarity | TrigramDistance` which
  evaluates to `None | None` → `TypeError` when `psycopg2` is not installed.
  Fixed by adding `from __future__ import annotations` to `filters.py`,
  making all annotations lazy strings that are never evaluated at class
  definition time.
- **`BaseRelatedFilter.get_queryset` assumes `.objects` manager** — same
  issue as `apply_cascade_permissions`. Changed `model.objects.all()` to
  `model._default_manager.all()`.
- **`BaseRelatedFilter.get_queryset` assertion crash when unbound** — the
  assertion message referenced `self.parent.__class__.__name__` which raises
  `AttributeError` if `self.parent` is `None` (unbound filter). Fixed with
  safe attribute chain via `getattr`.
- **`get_filterset_class` keyword collision** — if `extra_filter_meta`
  contained `filterset_base_class`, it was passed through `**meta` to
  `custom_filterset_factory` which also receives it as an explicit kwarg,
  causing `TypeError: multiple values for keyword argument`. Reserved keys
  are now stripped before passing.
- **`get_filterset_class` incorrect `**meta` type annotation** — changed
  `**meta: dict[str, Any]` to `**meta: Any` to match Python's variadic
  kwargs typing convention.
- **Aggregate `count` field name collision** — if a model field was
  literally named `count`, the per-field aggregate subtree overwrote the
  root total-row `count` scalar in the generated GraphQL type. The
  metaclass now raises `ValueError` at class creation if `"count"` appears
  in `Meta.fields`.
- **Aggregate field/relation name collision** — if a `Meta.fields` key
  matched a `RelatedAggregate` attribute name (e.g. both defining `values`),
  the relation overwrote the stat subtree. The metaclass now validates that
  the two sets are disjoint and raises `ValueError` on overlap.
- **Aggregate `datetime` category mixed field kinds** — `DateField`,
  `TimeField`, and `DurationField` were all mapped to the `"datetime"`
  category, causing min/max to declare `graphene.DateTime` in the schema
  even when the ORM returns `date`, `time`, or `timedelta`. Split into
  four categories: `"datetime"` (→ `DateTime`), `"date"` (→ `Date`),
  `"time"` (→ `Time`), `"duration"` (→ `Float` as total seconds).
- **Aggregate child queryset deduplication incomplete** —
  `get_child_queryset()` only applied `.distinct()` for `ManyToManyField`
  / `ManyToManyRel`, but reverse FK traversals (`ManyToOneRel`) can also
  produce duplicate rows, inflating `count`, `sum`, `mean`, and `uniques`.
  Now always applies `.distinct()` on child querysets — the cost on
  already-unique sets is negligible. Removed the now-unused
  `_is_m2m_lookup()` static method.
- **Aggregate `get_child_queryset` assumes `.objects` manager** — changed
  `target_model.objects.filter(...)` to
  `target_model._default_manager.filter(...)` for consistency with the
  same fix applied to `permissions.py` and `filters.py`.
- **`DJANGO_GRAPHENE_FILTERS = None` crashes attribute access** — if the
  Django setting was explicitly set to `None`, `user_settings` became
  `None` and `if name in self.user_settings` raised `TypeError`. Fixed by
  normalizing with `or {}`.
- **Fixed DB flags stale after `reload_settings`** — `IS_POSTGRESQL` and
  `HAS_TRIGRAM_EXTENSION` were cached at import time and never refreshed
  when Django's `setting_changed` signal fired (e.g. test suites swapping
  `DATABASES`). `reload_settings` now calls
  `get_fixed_settings.cache_clear()` and updates `FIXED_SETTINGS`.
- **Stray `# 4`, `# 3`, `# 2`, `# 1` comments in `conf.py`** — removed.
- **Missing `convert_enum` on flat filter arguments** — upstream
  graphene-django runs `convert_enum()` on every flat filter value so
  Graphene `Enum` inputs become plain Python values that django-filter
  expects. The override in `map_arguments_to_filters` was passing raw
  enum wrappers through, which could break validation or ORM lookups.
  Now imports and applies `convert_enum` from
  `graphene_django.filter.fields`.
- **`assert` for filterset class validation** — replaced `assert
  issubclass(...)` in `AdvancedDjangoFilterConnectionField.__init__` with
  an explicit `raise TypeError`. Assertions are stripped by `python -O`,
  allowing invalid filterset classes to slip through silently.
- **`map_arguments_to_filters` misleading docstring** — the docstring
  described `department_Name` → `department__name` transform logic that
  was never implemented. Replaced with accurate description of what the
  method actually does (filter + `convert_enum`).

## [0.7.1] - 2026-04-02

### Fixed

- **`_make_sentinel` crash on M2M fields** — `_make_sentinel` in
  `object_type.py` filtered FK fields using `hasattr(f, "attname")` which
  also matches `ManyToManyField`. Attempting `setattr` on an M2M field
  raises `TypeError: Direct assignment to the forward side of a
  many-to-many set is prohibited`. Fixed by using `hasattr(f, "column")`
  which only matches single-column relations (`ForeignKey` /
  `OneToOneField`), consistent with `permissions.py` and
  `mixins.get_concrete_field_names`.
- **`get_node` sentinel chain broken for Relay global IDs** — the sentinel
  short-circuit `if id == 0` did not match `"0"` (a string), which is what
  Relay's global ID decoder produces. Clients refetching a sentinel by its
  global ID would get `None` instead of a sentinel. Fixed by checking both
  `id == 0` and `id == "0"`.
- **Test warnings cleanup** — suppressed `InputObjectType` overwrite
  warnings in `test_aggregates_edge_aggregates.py` caused by test-ordering
  interactions with the global graphene type registry. Added
  `fields = "__all__"` to `ConnNode` and `test_advanced_django_object_type`
  to eliminate `DeprecationWarning` from graphene-django.

## [0.7.0] - 2026-04-02

### Added

- **`DISTINCT ON` support** — new `ASC_DISTINCT` and `DESC_DISTINCT` values on
  the `OrderDirection` enum. Fields marked with a `*_DISTINCT` direction define
  partition keys within `orderBy`; subsequent entries act as tie-breakers
  (determining which row survives per group).
  - **PostgreSQL** — uses native `DISTINCT ON` for optimal performance.
  - **All other backends** (SQLite, MySQL 8+, Oracle, MariaDB 10.2+) —
    emulated via `Window(RowNumber(), partition_by=..., order_by=...)`.
    Backend detection is automatic via the existing `IS_POSTGRESQL` flag.
  - **No new top-level argument** — distinct is expressed inline within the
    existing `orderBy` array, keeping the API surface minimal.
  - **Permission reuse** — `check_<field>_permission` methods on
    `AdvancedOrderSet` apply to `*_DISTINCT` directions identically to
    `ASC` / `DESC`.
  - **PostgreSQL ORDER BY deduplication** — `_apply_distinct_postgres`
    prevents invalid SQL (e.g. `ORDER BY name DESC, name ASC`) when the
    same field appears with contradictory directions by keeping only the
    first (distinct) entry.
  - **Blanket `.distinct()` skip** — `resolve_queryset` in
    `connection_field.py` skips the blanket `.distinct()` call when
    `*_DISTINCT` is active, since distinct-on already guarantees uniqueness.
- **Distinct integration tests** — `test_distinct.py` in the cookbook example
  with 10 tests covering: basic distinct, `DESC_DISTINCT`, boolean fields,
  filter + distinct, pagination, duplicate names, empty results, group
  elimination, unique value count, and regression (no distinct returns all).
- **Distinct unit tests** — 5 new `ASC_DISTINCT` / `DESC_DISTINCT` tests in
  `test_ordering.py` plus 3 `_apply_distinct_postgres` deduplication tests
  and 1 contradictory direction test.
- **Distinct-on spec** — `docs/distinct_on-spec.md` with full design rationale,
  edge cases (19 scenarios), stress tests (5 scenarios), database
  compatibility table, and future extensibility notes (`NULLS_FIRST` /
  `NULLS_LAST`).
- **99% coverage enforcement** — `[tool.coverage.report] fail_under = 99` in
  `pyproject.toml` and `--fail-under=99` in CI workflow.

### Changed

- **`get_flat_orders` return type** — **BREAKING**: returns
  `tuple[list[str], list[str]]` instead of `list[str]`. The second list
  contains bare field paths for fields whose direction was `*_DISTINCT`.
  External callers of this classmethod must destructure the return value:
  `flat_orders, distinct_fields = MyOrderSet.get_flat_orders(data)`.
- **`AdvancedOrderSet.__init__`** — now applies distinct-on after ordering
  when `_distinct_fields` is non-empty. Stores `_distinct_fields` on the
  instance for inspection by `connection_field.py`.

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
- **Computed fields** — `AdvancedFieldSet` can declare graphene type attributes
  (e.g. `display_name = graphene.String()`) that are automatically injected
  into the node type's schema via `_wrap_field_resolvers`.

### Changed

- **`_get_deny_value` caching** — deny values for field-level permission gates
  are now cached in a module-level dict by `(model, field_name)`. Epoch
  fallback constants (`_EPOCH_DATETIME`, `_EPOCH_DATE`) moved to module-level
  statics. Nullable fields short-circuit to `None` before default computation.

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

[0.7.2]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.7.2
[0.7.1]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.7.1
[0.7.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.7.0
[0.6.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.6.0
[0.5.2]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.5.2
[0.5.1]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.5.1
[0.5.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.5.0
[0.4.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.4.0
[0.3.1]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.3.1
[0.3.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.3.0
[0.2.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.2.0
[0.1.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.1.0
