# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--next-version-placeholder-->

## [Unreleased]

### Added

- **Multi-DB / sharding compatibility** — library-originated ORM queries
  now inherit the DB alias of the caller queryset (`queryset.db` /
  `self.queryset.db`), so shard-aware projects stop tripping
  cross-database subquery errors and stop silently probing the default
  alias. Single-DB behaviour is unchanged (all aliases resolve to
  `default`). Three fix sites:
  - `apply_cascade_permissions` — target-node visibility subquery is
    pinned to `queryset.db`.
  - `AdvancedAggregateSet.get_child_queryset` — related-aggregate child
    queryset is pinned to `self.queryset.db`.
  - `AdvancedDjangoObjectType.get_node` — captures the alias from the
    result of `cls.get_queryset(...)` and threads it into the hidden-row
    existence probe and the `_make_sentinel` call.
  See `docs/spec-db_sharding.md` for the alias-propagation rule,
  verified-safe call sites, and the two follow-up non-goals
  (`BaseRelatedFilter.get_queryset` form-validation path and
  `conf.py` capability detection).
- **`AdvancedDjangoObjectType._make_sentinel(*, using: str | None = None)`**
  — new keyword-only parameter on the protected sentinel builder. When
  provided, the FK-reload probe runs against
  `_default_manager.using(using)` so sentinel FK IDs come from the same
  shard the consumer's `get_queryset` selected.
- **`COOKBOOK_SHARDED=1` env-var toggle on `examples/cookbook/cookbook/settings.py`**
  — single `settings.py`, two **mutually exclusive** modes. Unset, the
  file declares `default` → `db.sqlite3` only (Django cannot see the
  shard files). Set to `1`, it declares `default` → `db_shard_a.sqlite3`
  and `shard_b` → `db_shard_b.sqlite3` only (Django cannot see
  `db.sqlite3`). Django requires a `default` entry, so under sharded
  mode `default` is the primary shard (shard A); `shard_b` is the
  explicit secondary. Day-to-day `runserver` / `uv run pytest` stays
  single-DB (byte-identical to consumer reality); the multi-DB suite is
  a second pass::

      uv run pytest                                                          # single-DB
      COOKBOOK_SHARDED=1 uv run pytest                                       # sharded

  `tests/test_db_sharding.py` has a module-level skip so it only runs
  when the `shard_b` alias is declared. Consumer projects do not need
  to mirror this layout — the library honours whatever alias the caller
  queryset carries via `queryset.db`.
- **`seed_shards` management command** — materializes
  `examples/cookbook/db_shard_a.sqlite3` and
  `examples/cookbook/db_shard_b.sqlite3` as committed, minimal-but-
  realistic shard DBs. Under sharded mode Django cannot see the dev
  `db.sqlite3`, so each shard is populated independently: (1) `migrate`,
  (2) `create_users(count=1, db_alias=alias)`, (3)
  `seed_data(count, db_alias=alias)` (default `count=1`). Re-run any
  time (every step is idempotent by username / seed count); grow with
  `--count` for local stress testing::

      COOKBOOK_SHARDED=1 uv run python examples/cookbook/manage.py seed_shards

- **`seed_data(count, db_alias="default")`** and
  **`create_users(count, db_alias="default")`** gained an optional
  `db_alias` parameter so the seeding service routes writes through
  `Model.objects.using(db_alias)` / `User.objects.db_manager(db_alias)`
  instead of always hitting `default`. Single-DB callers are unaffected.

### Changed

- **`AdvancedDjangoObjectType.get_node`** now seeds
  `cls.get_queryset(...)` with `cls._meta.model._default_manager.all()`
  instead of `cls._meta.model.objects`. This matches the existing
  `permissions.py` / `aggregateset.py` convention (supports models that
  override the default manager name) and is a prerequisite for reliably
  reading `queryset.db` on the result.
- **`AdvancedDjangoObjectType._make_sentinel`** FK-reload probe now uses
  `cls._meta.model._default_manager` instead of `.objects` for the same
  consistency reasons.

### Fixed

- **`ValueError: Subqueries aren’t allowed across different databases`**
  when `apply_cascade_permissions` or `get_child_queryset` received a
  queryset pinned to a non-default alias. The outer `__in` subquery now
  stays on the caller's alias.

## [1.0.0] - 2026-04-21

**Breaking release.** GraphQL input/output type names are now derived
from the declaring `AdvancedFilterSet` / `AdvancedOrderSet` /
`AdvancedAggregateSet` class name alone — no node-name prefix, no
traversal-path accumulation. Clients that hard-code generated type names
must regenerate; the schema SDL is self-describing and clients recompile
from the current output.

See `docs/spec-base_type_naming.md` for the full design, and
`docs/spec-remove-legacy-backward-compat.md` for the companion cleanup.

### Breaking Changes

- **Class-based GraphQL type naming** — every auto-generated type is now
  named after the declaring class rather than the traversal path. A
  `BrandFilter` reached from two different connections resolves to the
  same `BrandFilterInputType` both times, enabling Apollo / Pinia cache
  dedup. Concrete deltas:
  - `ToolToolFilterBrandNameFilterInputType` → `BrandFilterNameFilterInputType`
  - `ToolMetricToolMetricFilterToolBrandNameFilterInputType` → `BrandFilterNameFilterInputType`
  - `ToolToolOrderInputType` → `ToolOrderInputType`
  - `ObjectObjectAggregateAggregateType` → `ObjectAggregateType`
- **Removed `filter_input_type_prefix` / `order_input_type_prefix` kwargs**
  on `AdvancedDjangoFilterConnectionField`. Type names derive from the
  bound FilterSet / OrderSet class; the prefix kwargs no longer have a
  meaning. The previously-planned one-minor-version `DeprecationWarning`
  grace period was skipped — no external consumers.
- **Removed `input_type_prefix` parameter** from
  `FilterArgumentsFactory`, `OrderArgumentsFactory`, and
  `AggregateArgumentsFactory` `__init__`. Type names are derived from
  `filterset_class.type_name_for()` / `orderset_class.type_name_for()` /
  `aggregate_class.type_name_for()`.
- **Removed `OrderArgumentsFactory.create_order_input_type()`** (the
  legacy recursive helper). The public entry point is the `.arguments`
  property; emitted GraphQL types are cached in
  `OrderArgumentsFactory.input_object_types` keyed by
  `OrderSet.type_name_for()`.
- **Removed `FilterSetMetaclass.expand_auto_filter` and the `AutoFilter`
  class.** `AutoFilter` was a `django-rest-framework-filters`-era
  placeholder filter; every supported usage goes through `RelatedFilter`
  instead. `AdvancedFilterSet.get_filters()`'s dispatch inside the
  metaclass is now a single `expand_related_filter` call.
- **Removed `STAT_REGISTRY` backward-compat alias** and its singular
  callable helpers (`_py_median`, `_py_mode`, `_py_stdev`, `_py_variance`,
  `_bool_true_count`, `_bool_false_count`). The 0.7.5 consolidation
  refactor made these unreachable. `DB_AGGREGATES` / `PYTHON_STATS` /
  `SPECIAL_STATS` / `DB_NATIVE_PERCENTILE_STATS` are the only stat
  registries going forward.
- **Removed `setup_filterset` wrap in `get_filterset_class`** for
  `AdvancedFilterSet` subclasses. Non-Advanced classes are no longer
  supported — passing one raises `TypeError` at the connection-field
  init, which validated subclasses upfront already.
- **`RelatedFilter(X, field_name="foo")` plus `Meta.fields = {"foo":
  ["in"]}` is no longer supported.** Under class-based naming the field
  becomes a lambda ref to the target's root type; the direct `foo.in`
  lookup is silently dropped. Filter via the nested target filterset
  instead (e.g. `role: { name: { in: [...] } }`).
- **Collision detection is strict-raise, not warn.** Two distinct
  classes claiming the same `type_name` now trigger
  `TypeError("Class-based naming collision: ...")` at schema build.
  Under class-based naming a collision is a bug, not a user-input issue.

### Added

- **`type_name_for(field_path=None)` classmethod** on
  `AdvancedFilterSet`, `AdvancedOrderSet`, `AdvancedAggregateSet` —
  produced by the new `ClassBasedTypeNameMixin` in `mixins.py`. Each
  base set sets `_root_type_suffix` and `_field_type_suffix` class
  attributes; the mixin handles both simple field names and
  `LOOKUP_SEP`-separated nested paths (`created__date__year` →
  `CreatedDateYear`).
- **`utils.raise_on_type_name_collision`** — shared strict-raise
  collision guard consumed by all three argument factories. Error
  message names both modules + qualnames:
  `TypeError("Class-based naming collision: GraphQL type '{type_name}'
  is already registered by '{prior.__module__}.{prior.__qualname__}'
  but now '{cls.__module__}.{cls.__qualname__}' is trying to claim
  the same name. Rename one of the {kind} classes.")`.
- **BFS + lambda-ref factory pattern** — `FilterArgumentsFactory`,
  `OrderArgumentsFactory`, and `AggregateArgumentsFactory` each walk
  the root class plus every reachable related-* descendant, build one
  GraphQL type per class, and emit lambda refs at
  `RelatedFilter` / `RelatedOrder` / `RelatedAggregate` boundaries.
  Replaces the previous inline-subtree + `_building` cycle-guard
  approach. Cycles resolve naturally at schema-finalize time.
- **`_dynamic_filterset_cache`** in `filterset_factories.py` —
  memoizes dynamically-generated `AdvancedFilterSet` subclasses (from
  the `filterset_class=None` auto-generation path triggered by
  `filter_fields` on a node type) by `(model, fields_key, extra)`.
  Without this, two connection fields on the same model would fabricate
  two distinct classes sharing the same `__name__` and trip the
  collision check.
- **`GrapheneFilterSetMixin` is a direct base of `AdvancedFilterSet`.**
  Previously the mixin was applied only at the top level via
  graphene-django's `setup_filterset` wrapper, which produced a
  divergent `Graphene{X}Filter` class name relative to nested
  `RelatedFilter` traversals. Now every `AdvancedFilterSet` subclass
  carries `FILTER_DEFAULTS` (the `GlobalIDFilter` overrides on FKs /
  PKs) uniformly, and the wrapper is skipped.
- **`utils.raise_on_type_name_collision`, `ClassBasedTypeNameMixin`,
  `_bound_class_property_pair` helper** and the shared
  `QuerySetProxy._combine` method consolidate near-duplicate code
  across filter / order / aggregate factories and the connection field
  — three "provided vs resolved class" property pairs collapse into a
  single helper; three per-factory `_check_collision` methods become
  one utility function; three per-class `type_name_for` classmethods
  become one mixin.

### Changed

- **`compute()` and `acompute()` in `AdvancedAggregateSet`** share the
  new `_related_plan(selection_set)` helper that returns
  `(rel_name, rel_agg, child_selection)` triples. Selection-set gating
  and iteration order now live in a single place, guaranteeing sync
  and async outputs stay byte-identical.
- **`AdvancedDjangoFilterConnectionField`** gained a
  `_bound_class_property_pair(kind)` helper that generates both
  `provided_<kind>_class` and `<kind>_class` properties for
  `aggregate` and `orderset` from the instance-layout contract
  (`_provided_<kind>_class` + `_<kind>_class`). `filterset_class`
  retains its custom logic because it calls `get_filterset_class`.
  Fixes a latent inconsistency where `provided_filterset_class` used
  direct attribute access while the other two used `getattr(_meta,
  ..., None)`.
- **`QuerySetProxy.filter_` and `exclude_`** collapsed to one-line
  delegates over a shared `_combine(negate, *args, **kwargs)` helper.

### Removed

- `filter_input_type_prefix` and `order_input_type_prefix` kwargs on
  the connection field.
- `input_type_prefix` kwarg on all three argument factories.
- `OrderArgumentsFactory.create_order_input_type`.
- `FilterSetMetaclass.expand_auto_filter` and the `AutoFilter` class.
- `STAT_REGISTRY` alias + singular `_py_*` / `_bool_*` helpers.
- `setup_filterset` wrapping in `get_filterset_class` (for
  `AdvancedFilterSet` subclasses).
- Redundant `if ag_class in seen: continue` / `if fs_class in seen:
  continue` / `if os_class in seen: continue` pop-time cycle guards
  — the enqueue-time `target not in seen` gate handles cycles
  identically.
- Paranoid `f.__class__.__name__.endswith("RelatedFilter")` double-check
  in `_get_trimmed_filterset_class` — `isinstance(f, BaseRelatedFilter)`
  already covers it.
- Unreachable `TypeError` gate in `filterset_factories.get_filterset_class`
  — `AdvancedDjangoFilterConnectionField.__init__` validates the
  subclass upstream with a clearer message.
- Orphaned docstring references to `rest_framework_filters` and the
  stale "DEFER EXPANSION" comment in `FilterSetMetaclass.__new__`.

### Fixed

- **`ForeignKey + __in` crash under `GrapheneFilterSetMixin` documented
  as a known pitfall.** Adding the mixin to `AdvancedFilterSet` surfaced
  an upstream graphene-django quirk: `GRAPHENE_FILTER_SET_OVERRIDES`
  maps `ForeignKey → GlobalIDFilter` (singular `GlobalIDFormField`),
  which cannot handle a list value when `lookup_expr="in"`. The
  resulting error is a cryptic `TypeError: argument should be a
  bytes-like object or ASCII string, not 'list'` from `base64`. The
  library does not ship a workaround beyond filtering via the nested
  target filterset; `docs/fix-graphene-django-AdvancedFilterSet.md`
  drafts the upstream fix (promote `GlobalIDFilter` →
  `GlobalIDMultipleChoiceFilter` when `lookup_expr in ("in", "range")`).
- **Latent `provided_filterset_class` inconsistency** — used direct
  attribute access (`self.node_type._meta.filterset_class`) while the
  aggregate / orderset counterparts used `getattr(..., None)`. All
  three now route through the same `_bound_class_property_pair` helper
  with uniform safe `getattr` semantics.
- **Mixed nested / top-level FilterSet schema divergence** — the old
  `setup_filterset` wrap produced `Graphene{X}FilterInputType` at
  top-level while nested `RelatedFilter` traversals used the raw user
  class's name `{X}FilterInputType`. Two different types for the same
  logical FilterSet defeated class-based cache dedup. Now a single
  canonical type name applies everywhere.

### Coverage & Tests

- **100% line + branch coverage** across all 20 modules; enforced by
  `uv run coverage report --fail-under=100`.
- **13 new tests** in `tests/test_coverage_gaps.py` closing specific
  branches: `RelatedAggregate(None, ...)` skip, `HIDE_FLAT_FILTERS=True`
  branch, `RelatedFilter(None, ...)` drop, trigram-child routing, non-leaf
  field-name recursion, `_get_fields` empty-target branch, dict and raw
  cache-key paths in `_make_cache_key`, NOT subquery `None` return,
  async aggregate pre-agg-set dispatch, and two `DISTINCT ON` edge
  cases on `AdvancedOrderSet`.
- **Test-layer pruning** — deleted tests for the removed `AutoFilter`,
  `STAT_REGISTRY`, singular `_py_*` / `_bool_*` helpers, the old
  prefix properties / kwargs, and the old collision-warning semantics.
  Rewrote `test_user_profile_role_o2m` to filter by scalar role name
  (avoiding the graphene-django `FK + __in` pitfall).
- **Stale line-number comments** (~30 sites across 8 test files)
  replaced with intent-first docstrings — `"``get_filter_fields``
  explicitly adds ``'search'`` to the returned dict"` instead of
  `"Test get_filter_fields explicitly adds 'search' (Lines 458-460)."`.

### Docs

- `docs/spec-base_type_naming.md` — full design for class-based naming,
  migration plan, and open questions.
- `docs/spec-remove-legacy-backward-compat.md` — single-consumer
  library rationale, file-by-file checklist for the cleanup pass, and
  non-goals.
- `docs/fix-graphene-django-AdvancedFilterSet.md` — upstream-PR brief
  for the graphene-django `FK + __in` + `GlobalIDFilter` singular-field
  limitation.
- `AGENTS.md` — new sections on class-based naming consequences,
  testing conventions, known graphene-django pitfalls, and a
  refactoring / cleanup playbook.

## [0.7.5] - 2026-04-17

### Added

- **Query-consolidated `AdvancedAggregateSet.compute()`** — the per-stat
  `STAT_REGISTRY` dispatch was replaced by a **plan → execute → assemble**
  pipeline (see `docs/spec-async_and_query_consolidation.md`). Stats are
  now classified into four registries — `DB_AGGREGATES`, `PYTHON_STATS`,
  `SPECIAL_STATS`, and PostgreSQL-only `DB_NATIVE_PERCENTILE_STATS` — and
  a single `.aggregate(**kwargs)` call carries every DB-level stat for
  every field in one roundtrip. Python-level stats
  (`median`/`mode`/`stdev`/`variance`) now share **one**
  `_fetch_values()` call per field rather than one per stat. Observable
  effect: a five-stat config on one field drops from ~5 DB queries to 2
  (root `count()` + consolidated `aggregate()`), with no change to the
  returned dict shape, selection-set behaviour, permission cascades,
  custom stats, or `compute_<field>_<stat>()` overrides. The
  `STAT_REGISTRY` symbol is preserved as a backward-compat alias for
  any third-party code that imports it.
- **`acompute()` async variant on `AdvancedAggregateSet`** — returns
  identical output to `compute()` but runs own-field work via
  `sync_to_async(..., thread_sensitive=True)` and fans
  `RelatedAggregate` traversals out with `asyncio.gather`. Intended for
  ASGI resolvers; thread-sensitive mode preserves `ATOMIC_REQUESTS`
  transaction semantics (see the spec's §6.4 for the trade-offs). Sync
  `compute()` behaviour is unchanged.
- **`ASYNC_AGGREGATES` setting** — new entry in `DJANGO_GRAPHENE_FILTERS`
  (default `False`) that controls how
  `AdvancedDjangoObjectType.resolve_aggregates` dispatches. When `True`,
  the resolver returns the `acompute()` coroutine so Graphene's async
  executor awaits it; when `False`, the sync `compute()` is called and
  a plain `dict` is returned. This is an **explicit opt-in** rather than
  an event-loop probe — a caller inside `asyncio.run(...)` invoking the
  schema synchronously would otherwise get back an unawaited coroutine.
  Both the root-level and nested-connection paths share the same
  dispatch logic, so flipping the setting covers every aggregate
  resolver in the schema. `conf.py` documents when to flip it in full.

  ```python
  # settings.py
  DJANGO_GRAPHENE_FILTERS = {
      "ASYNC_AGGREGATES": True,  # ASGI + Graphene async executor only
  }
  ```
- **PostgreSQL-native `stdev` and `variance`** — when
  `settings.IS_POSTGRESQL` is true, these stats route through Django's
  `StdDev(..., sample=True)` / `Variance(..., sample=True)` aggregates
  inside the consolidated `.aggregate()` call instead of fetching the
  full values list into Python. Removes the `AGGREGATE_MAX_VALUES`
  truncation for these stats on PostgreSQL — results become exact.
  Rounding to 2 d.p. is applied in the assemble phase so output stays
  bit-identical with the SQLite fallback. `median` and `mode` remain in
  Python on all backends (Django does not ship cross-backend
  `PercentileCont` / `Mode` aggregates; see the spec's §5 open
  questions).

### Changed

- **Root-level aggregate resolution deferred to resolve-time** —
  `AdvancedDjangoFilterConnectionField.resolve_queryset` previously
  precomputed root-level aggregates synchronously and attached the
  result to the queryset as `_aggregate_results`. It now stashes the
  pre-built aggregate set and the extracted GraphQL selection on the
  queryset (`_aggregate_set`, `_aggregate_selection`) and defers the
  actual computation to `resolve_aggregates`. This lets root-level
  queries participate in the new `ASYNC_AGGREGATES` dispatch on the
  same footing as nested connections — previously only the nested path
  could reach `acompute()`. The dead `resolve_connection` override that
  read the stale `_aggregate_results` attribute was removed.

### Fixed

- **Consolidated-aggregate alias collision on underscore boundaries** —
  the initial consolidation refactor encoded ``.aggregate()`` kwargs as
  ``f"_agg_{field}_{stat}"``. That form is not injective once either name
  contains underscores: ``(field="x_true", stat="count")`` and
  ``(field="x", stat="true_count")`` both resolved to
  ``_agg_x_true_count``. The second overwrote the first in both
  ``agg_kwargs`` and ``agg_lookup``, and the assemble phase returned the
  wrong value (or silently dropped one stat). `_alias()` is now
  counter-based via ``itertools.count()`` — aliases are unique by
  construction regardless of field or stat names. ``agg_lookup`` remains
  the source of truth for ``(field, stat) → alias`` so assembly is
  unchanged.
- **Async resolver dispatch for aggregates** — `acompute()` was added on
  `AdvancedAggregateSet` earlier in this release but no resolver
  actually called it, leaving it dead code in the library's own
  integration (see `docs/review.md`). Root-level aggregates were also
  precomputed synchronously before the resolver ran, so even the
  addition of an async resolver branch couldn't reach them. The initial
  fix probed `asyncio.get_running_loop()` to decide whether to return a
  coroutine, but that conflates "event loop exists" with "Graphene is
  awaiting this resolver" — a sync invocation from inside
  `asyncio.run(...)` would have received an unawaited coroutine. The
  dispatch now reads the new explicit `ASYNC_AGGREGATES` setting at
  call time, and both root-level and nested paths consume the stored
  `_aggregate_set` / lazy-per-edge set respectively so they share the
  same sync/async branches.
- **PostgreSQL `*_DISTINCT` crashes on aggregate-annotated querysets** —
  the PostgreSQL native path called `.distinct(*fields)` on querysets
  that may already have aggregate annotations from earlier filter steps
  (e.g. via `AnnotatedFilter` subclasses or `AggregateArgumentsFactory`).
  Django raises `NotImplementedError: annotate() + distinct(fields) is
  not implemented.` whenever `GROUP BY` is present. `apply_distinct` now
  detects `queryset.query.group_by` and falls back to the
  `Window(RowNumber())` emulation when it's truthy — keeping the native
  fast path for simple querysets while handling the aggregate case
  correctly.
- **`RelatedAggregate` declarations not inherited by subclasses** —
  symmetric to the `OrderSetMetaclass` fix: `AggregateSetMetaclass`
  built `related_aggregates` from the current class's `attrs` only,
  silently stripping every inherited `RelatedAggregate` from base
  classes. Subclassing an `AdvancedAggregateSet` caused `compute()` /
  `acompute()` to lose relationship aggregate traversal, and
  `AggregateArgumentsFactory.build_aggregate_type` would omit the
  related fields from the GraphQL output type entirely. The metaclass
  now walks bases in MRO order first, applies the current class's
  declarations on top, and calls `bind_aggregateset` on the merged set
  — in both the abstract-base branch and the normal path — so an
  intermediate abstract class (`Meta.model = None`) also propagates
  inherited relations to its own subclasses.
- **`RelatedOrder` declarations not inherited by subclasses** —
  `OrderSetMetaclass` built `related_orders` from the current class's
  `attrs` only, silently stripping every inherited `RelatedOrder` from
  base classes. Subclassing an `AdvancedOrderSet` caused `get_fields`,
  `get_flat_orders`, and `check_permissions` to all lose relationship
  ordering support. The metaclass now walks base classes in MRO order
  first, then applies the current class's declarations on top
  (matching Python's method resolution semantics — a subclass can still
  override an inherited `RelatedOrder` by redeclaring it).
- **`AdvancedFilterSet._expanded_filters` cache leaked across subclasses via MRO** —
  `get_filters()` read the cache with `getattr(cls, "_expanded_filters", None)`
  which walks the MRO, so a subclass whose parent had already been
  expanded would silently return the parent's cached dict and skip its
  own expansion. Subclass-level `RelatedFilter` additions or
  `Meta.fields` changes never reached the schema or runtime. The cache
  and the in-progress `_is_expanding_filters` flag are now read via
  `cls.__dict__` so each class caches strictly for itself — a
  mid-expansion parent can also no longer short-circuit a subclass that
  happens to sit in the same MRO chain.
- **Bare transform lookups omitted from `__all__` filter generation** —
  `lookups_for_field` only emitted expanded sub-lookups for transforms
  (e.g. `date__exact`, `date__lt`) but never the bare transform form
  (e.g. `date`). `filter(created__date=today)` is valid ORM shorthand for
  `filter(created__date__exact=today)` and is supported by django-filter, so it
  should be included when a field is declared as `"__all__"`. Both
  `lookups_for_field` and `lookups_for_transform` now emit the bare transform
  expression before the expanded sub-lookups.
- **Multi-transform cycle recursion in `lookups_for_transform`** —
  the existing `type(transform) is lookup` guard only caught direct
  self-loops (`a__a__…`, e.g. `Unaccent` registered on its own output
  field). Chains that cycle through two or more transform classes
  (`a__b__a__b__…`) would recurse until `RecursionError`. The function
  now threads a `frozenset[type[Transform]]` of visited classes through
  the recursion and skips any Transform class already present in the
  chain, terminating both direct and multi-step cycles safely. The
  parameter is internal (`_visited`); callers still invoke
  `lookups_for_transform(transform)` as before.
- **Transform-own lookups ignored during lookup discovery** —
  `lookups_for_transform` only inspected `transform.output_field.get_lookups()`,
  bypassing any lookups registered directly on the transform class itself
  (e.g. via `MyTransform.register_lookup(SomeLookup)`). Since `Transform`
  inherits from `RegisterLookupMixin`, transform classes can carry their own
  `class_lookups`. The function now merges both sources, with transform-own
  entries taking precedence, so custom and third-party transforms that expose
  extra operators are fully discovered.
- **`BaseRelatedOrder` and `RelatedOrder` spurious `*args, **kwargs` removed** —
  both `__init__` methods accepted `*args, **kwargs` and forwarded them to
  `super().__init__()`, but `LazyRelatedClassMixin` → `object` accepts no
  extra arguments. Passing unexpected kwargs would raise `TypeError:
  object.__init__() takes exactly one argument`. The signatures now
  accurately reflect what is accepted: `BaseRelatedOrder(orderset)` and
  `RelatedOrder(orderset, field_name)`.

### Notes

- **Blanket `.distinct()` in `resolve_queryset` is safe on aggregate-annotated
  querysets.** An investigation confirmed that `connection_field.py`'s
  plain `qs.distinct()` (no field args) does **not** have the same
  failure mode as the `.distinct(*fields)` path fixed in
  `AdvancedOrderSet.apply_distinct`. Django wraps the DISTINCT select
  in a subquery for any subsequent `.aggregate()` call, so the later
  `count()` / `.aggregate(**kwargs)` calls made by the aggregate
  pipeline still return correct results even when
  `qs.query.group_by` is set. No `has_group_by` gate is required here;
  regression tests lock the behaviour in.

## [0.7.4] - 2026-04-04

### Added

- **`HIDE_FLAT_FILTERS` setting** — when set to `True` in
  `DJANGO_GRAPHENE_FILTERS`, the flat snake_case filter arguments
  (e.g. `brand_Link_In`, `category_Description_Istartswith`) are omitted
  from the GraphQL schema. They no longer appear in GraphiQL
  autocomplete or schema introspection, reducing clutter on models with
  many related filters. The nested `filter: { ... }` tree, Relay
  pagination (`first`, `last`, `before`, `after`), `orderBy`, and
  `search` arguments are unaffected. Defaults to `False` (existing
  behaviour unchanged).

  ```python
  # settings.py
  DJANGO_GRAPHENE_FILTERS = {
      "HIDE_FLAT_FILTERS": True,
  }
  ```

## [0.7.3] - 2026-04-04

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
- **CI pipeline** — GitHub Actions testing across Python 3.10-3.14 × Django
  5.1 / 5.2 / 6.0 / latest with coverage uploaded to Coveralls.

[0.7.5]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.7.5
[0.7.4]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.7.4
[0.7.3]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.7.3
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
