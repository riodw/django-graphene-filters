# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

`django-graphene-filters` is a Python library providing advanced auto-related filters for graphene-django. It extends `django-filter` and `graphene-django` with nested/tree-structured filtering (AND/OR/NOT), related model traversal via `RelatedFilter`, ordering via `AdvancedOrderSet`, full-text search (PostgreSQL SearchVector/SearchRank/Trigram), per-field permission checks, and cascade FK visibility via `apply_cascade_permissions`.

**This is a single-consumer library.** There are no external users relying on deprecated API surface area. Deletes beat deprecations — don't add `DeprecationWarning` shims unless there's a concrete consumer that justifies them.

## Development Commands

### Setup
```
uv sync
```

### Running Tests
```
# All tests (uses examples/cookbook as Django settings via pytest.ini)
uv run pytest

# Single test file
uv run pytest tests/test_filterset_advanced.py

# Single test
uv run pytest tests/test_filterset_advanced.py::TestClassName::test_method_name -v

# With coverage (100% coverage is enforced)
uv run coverage run -m pytest
uv run coverage report --fail-under=100
uv run coverage report --show-missing

# Coverage for a specific module
uv run coverage run -m pytest tests/test_input_data_factories.py && uv run coverage report -m django_graphene_filters/input_data_factories.py
```

### Formatting and Linting
```
uv run ruff format .
uv run ruff check --fix .
```

**Always run both commands after making any code changes.** Line length is 110 (see `pyproject.toml [tool.ruff]`). Ruff enforces Google-style docstrings (`D`), type annotations (`ANN`), and isort (`I`) among others. Tests and examples have relaxed rules (see `pyproject.toml [tool.ruff.lint.per-file-ignores]`).

### Running the Example App
```
uv run python examples/cookbook/manage.py runserver
uv run python examples/cookbook/manage.py seed_data       # seed 5 objects per provider
uv run python examples/cookbook/manage.py seed_data 50    # seed 50
```

### Build and Publish
```
uv lock
uv build
uv publish --token PASSWORD
```

### Version Bumps
Version must be updated in three places:
- `pyproject.toml` (line ~4)
- `django_graphene_filters/__init__.py` (`__version__`)
- `tests/test_django_graphene_filters.py`

## Architecture

### Core Pipeline

The library replaces graphene-django's `DjangoFilterConnectionField` with its own connection field that processes nested filter/order trees:

1. **`AdvancedDjangoFilterConnectionField`** (`connection_field.py`) — The GraphQL field users attach to their schema's `Query` class. It orchestrates everything: builds filtering args via `FilterArgumentsFactory`, ordering args via `OrderArgumentsFactory`, and resolves querysets by merging advanced (tree) and flat (standard) filter data.

2. **`AdvancedFilterSet`** (`filterset.py`) — Replaces django-filter's `FilterSet`. Uses a custom `FilterSetMetaclass` that discovers `RelatedFilter` declarations and lazily expands them into flattened ORM lookups (e.g., `object_type__name__icontains`). The `filter_queryset` method walks a tree of AND/OR/NOT forms using `QuerySetProxy` — a wrapper around Django's `QuerySet` that accumulates `Q` objects instead of applying filters directly, enabling logical combination and negation.

3. **`FilterArgumentsFactory`** (`filter_arguments_factory.py`) — Converts the expanded filterset into a nested GraphQL `InputObjectType` tree using `anytree.Node`. Each filter's `field_name + lookup_expr` path becomes a nested structure (e.g., `filter { objectType { name { icontains: "..." } } }`), plus AND/OR/NOT fields for logical combination.

4. **`input_data_factories.py`** — Reverse of the arguments factory: converts the incoming GraphQL `InputObjectTypeContainer` tree back into flat `{key: value}` data that `AdvancedFilterSet` understands. Contains special-case factories for full-text search types (SearchQuery, SearchRank, Trigram).

### Ordering System

Parallel to filtering, ordering uses its own class hierarchy:

- **`AdvancedOrderSet`** (`orderset.py`) — Metaclass-driven like filtersets. Declares `RelatedOrder` fields for traversing relationships. Recursively flattens nested GraphQL input `[{objectType: {name: ASC}}]` into Django `order_by()` args like `["object_type__name"]`.
- **`OrderArgumentsFactory`** (`order_arguments_factory.py`) — Builds the `orderBy` GraphQL argument as a `List(InputObjectType)` with an `OrderDirection` enum (ASC/DESC).

### Filters (`filters.py`)

- **`RelatedFilter`** — The key filter type. Accepts a filterset class (or string for lazy/circular resolution via `LazyRelatedClassMixin`) and a `field_name`. The metaclass expands it by pulling in the target filterset's filters with prefixed field names.
- **`AnnotatedFilter`** and subclasses (`SearchQueryFilter`, `SearchRankFilter`, `TrigramFilter`) — PostgreSQL full-text search filters that annotate querysets before filtering. Only active when `IS_POSTGRESQL` is true (checked at startup in `conf.py`).

### Key Patterns

- **Lazy class resolution**: Both `RelatedFilter` and `RelatedOrder` accept string references (e.g., `"ValueFilter"`) to handle circular dependencies. Resolution happens via `LazyRelatedClassMixin.resolve_lazy_class()`, which tries absolute import then falls back to the bound class's module.
- **Recursion protection**: `AdvancedFilterSet.get_filters()` uses `_is_expanding_filters` flag to prevent infinite loops when circular `RelatedFilter` references trigger mutual expansion.
- **`QuerySetProxy`** (`filterset.py`) — Wraps a QuerySet using `wrapt.ObjectProxy`, intercepting `.filter()` and `.exclude()` to build a `Q` object tree rather than immediately querying the database. This enables the AND/OR/NOT logical tree to be evaluated correctly.
- **`InputObjectTypeFactoryMixin`** (`mixins.py`) — Shared caching for dynamically created Graphene `InputObjectType` classes, used by both filter and order argument factories.

### Django Settings Integration

`conf.py` exposes a `settings` singleton configurable via `DJANGO_GRAPHENE_FILTERS` in Django's `settings.py`. Keys: `FILTER_KEY` (default `"filter"`), `AND_KEY`, `OR_KEY`, `NOT_KEY`. Fixed settings `IS_POSTGRESQL` and `HAS_TRIGRAM_EXTENSION` are auto-detected at startup (with graceful fallback if the DB is unreachable).

### Test Configuration

Tests use `pytest-django` with `DJANGO_SETTINGS_MODULE = examples.cookbook.cookbook.settings` (defined in `pytest.ini`). The cookbook app uses SQLite, so PostgreSQL-specific features (full-text search, trigram) are tested with mocks/patches where needed.

### Permissions & Cascade Visibility

- **`apply_cascade_permissions`** (`permissions.py`) — Utility function for use inside `get_queryset`. Filters out rows whose FK targets are hidden by the target node's `get_queryset`. Uses `contextvars.ContextVar` for async-safe cycle detection. Accepts an optional `fields` parameter to limit which FKs are cascaded.
- **Sentinel nodes** — `AdvancedDjangoObjectType.get_node()` returns a redacted sentinel instance (`pk=0`) instead of `None` when `get_queryset()` hides a row. Sentinels copy real FK IDs from the hidden row so visible downstream targets resolve normally; hidden targets produce their own sentinels recursively.
- **`isRedacted: Boolean!`** — Computed field on every `AdvancedDjangoObjectType`. Returns `true` for sentinel nodes, `false` for real rows. Clients query this to detect redacted FK targets.
- **Relay Node warning** — `AdvancedDjangoObjectType` emits a `UserWarning` if a subclass lacks the Relay `Node` interface, since sentinels and cascade permissions require `get_node` for FK resolution.
- **Per-field permission checks** — Convention-based `check_{field}_permission(request)` methods on `AdvancedFilterSet` and `AdvancedOrderSet`. Auto-invoked during `__init__` for every field in the incoming data. Delegated through `RelatedFilter`/`RelatedOrder` chains.

### `AdvancedDjangoObjectType` (`object_type.py`)

Extends `DjangoObjectType` to support `orderset_class`, `search_fields`, and `isRedacted` in Meta. Overrides `get_node()` with sentinel behaviour. Warns if Relay `Node` interface is missing.

## Class-Based GraphQL Naming (post-1.0.0)

See `docs/spec-base_type_naming.md`. Every auto-generated GraphQL type name derives from the declaring class's `__name__` alone — no node-name prefix, no traversal-path accumulation. Two separate connections reaching the same `BrandFilter` both resolve to `BrandFilterInputType`, enabling Apollo / Pinia cache dedup.

Key consequences to remember when editing factories:

- **`AdvancedFilterSet` inherits `GrapheneFilterSetMixin` directly** (not via graphene-django's `setup_filterset` wrap). `get_filterset_class` returns the user class unchanged for any `AdvancedFilterSet` subclass; the `Graphene{X}Filter` wrapper name would otherwise diverge from nested `RelatedFilter` traversals.
- **BFS + lambda refs** pattern in all three factories (`FilterArgumentsFactory`, `OrderArgumentsFactory`, `AggregateArgumentsFactory`): each factory's `_ensure_built` walks the root class plus every related-* descendant, building one GraphQL type per class. `RelatedFilter` / `RelatedOrder` / `RelatedAggregate` boundaries emit `graphene.InputField(lambda tn=...: self.input_object_types[tn])` refs rather than inline subtrees. Cycles resolve at schema-finalize time.
- **Shared helpers** live in `utils.py` (`raise_on_type_name_collision`) and `mixins.py` (`ClassBasedTypeNameMixin`). Each of the three base sets sets `_root_type_suffix` / `_field_type_suffix` class attributes; don't reintroduce per-class `type_name_for` overrides.
- **Collision check is strict-raise, not warn.** Two distinct classes claiming the same `type_name` → `TypeError("Class-based naming collision: ...")`. Under class-based naming a collision is a bug, not a warning-worthy user input issue.
- **Dynamic `filterset_class=None` path** (when a node type declares `filter_fields` instead of `filterset_class`) is memoized in `filterset_factories._dynamic_filterset_cache` by `(model, fields_key, extra)`. Without memoization, two connection fields on the same model would fabricate two distinct classes with the same `__name__` and trip the collision check.

## Testing Conventions

### Invariants to keep

- **100% line + branch coverage is enforced** (`uv run coverage report --fail-under=100`). CI catches regressions; land any fix + test in the same change.
- **Mock the behaviour, not the class.** Avoid the `MagicMock()` + `.__name__ = "X"` anti-pattern — the new factory calls `cls.type_name_for()` which returns another MagicMock and crashes `type(...)`. Prefer real tiny `AdvancedFilterSet` / `AdvancedOrderSet` / `AdvancedAggregateSet` subclasses; mock only the specific method the test cares about (e.g. `compute`).
- **Describe what, not where, in docstrings.** Line-number comments (`"Line 148: ..."`) drift with every edit and mislead new contributors. Use verbs: `"``get_filter_fields`` explicitly adds ``'search'`` to the returned dict."`
- **Factory caches persist across tests.** `FilterArgumentsFactory.input_object_types`, `_type_filterset_registry`, and the analogous aggregate/order registries are class-level dicts. Hermetic tests must `pop(type_name, None)` before priming. The pattern is already established — follow it.
- **Tests for removed code go with the code.** When pruning legacy, sweep `tests/` for imports and assertions on the removed symbols in the same change. Don't leave orphan tests with broken imports.

### What triggers which factory branch

Tree-building in `filter_arguments_factory.py` has some non-obvious rules:

- **`filterset_to_trees` splits `field_name` on `LOOKUP_SEP` but appends `lookup_expr` as a single node.** `field_name="object_type__name"`, `lookup_expr="exact"` → sequence `("object_type", "name", "exact")`. `field_name="created_at"`, `lookup_expr="year__gt"` → sequence `("created_at", "year__gt")` (two elements, not three). To exercise the recursive `else` branch of `_build_path_subfield` you need a multi-segment `field_name`, not a multi-segment `lookup_expr`.
- **`DEFAULT_LOOKUP_EXPR` ("exact") is stripped from filter names.** `field_name="created_at"` + `lookup_expr="year__exact"` is stored under the key `created_at__year`, not `created_at__year__exact` — django-filter's `get_filter_name` trims a trailing `exact`. Declaring `fields = {"foo": ["year", "year__exact"]}` produces two filters with the *same* key (the second overwrites), which is rarely what you want.
- **Mixing `RelatedFilter(X, field_name="foo")` with a direct `Meta.fields = {"foo": ["in"]}` lookup is not supported.** The lambda ref to `X`'s root type wins and the direct lookup is silently dropped from the schema. Filter via the nested target filterset instead.
- **`RelatedFilter(None, ...)` / `RelatedOrder(None, ...)` / `RelatedAggregate(None, ...)` are supported placeholders** that drop out of the emitted schema instead of raising. Edge cases covered by dedicated tests; don't remove the `is not None` guards in the three factories.

## Known graphene-django Pitfalls

### `ForeignKey + __in` is broken under `GrapheneFilterSetMixin`

Declaring `Meta.fields = {"fk_field": ["in"]}` on an `AdvancedFilterSet` crashes with:

```
TypeError: argument should be a bytes-like object or ASCII string, not 'list'
```

Root cause: `GRAPHENE_FILTER_SET_OVERRIDES` maps `ForeignKey → GlobalIDFilter` (singular `GlobalIDFormField`). When `lookup_expr="in"`, the filter receives a list but tries to base64-decode it as one scalar ID. See `docs/fix-graphene-django-AdvancedFilterSet.md` for the upstream fix brief.

**Workarounds**:
- Filter via the nested target filterset by a scalar (e.g. `role: { name: { in: [...] } }`) instead of by FK ID.
- Explicitly declare `GlobalIDMultipleChoiceFilter` on the filterset.

## Refactoring / Cleanup Playbook

### Finding dead code

Two complementary tools; use both.

1. **Keyword grep** for self-announcing legacy: `TODO`, `DEPRECATED`, `LEGACY`, `backward`, `# compat`, `rest_framework_filters`. Good for finding code that announces itself as old (e.g. a `STAT_REGISTRY` aliased as "backward-compat").
2. **Coverage analysis** (`uv run coverage report --show-missing`). Strictly stronger for *new* code because it doesn't care what the code looks like — only whether anything runs it. Always run coverage *before* the keyword grep, not after.

A pattern-grep sweep will miss redundant defensive code added in the same session (e.g. BFS cycle guards made redundant by a sibling `seen` check at enqueue time). Coverage catches those because the branch never fires.

### Cleanup order

1. Remove code that announces itself as legacy (`STAT_REGISTRY`, `AutoFilter`, `*_input_type_prefix` kwargs, `setup_filterset` fallback).
2. Sweep tests: drop any test that imports a removed symbol or asserts on removed behaviour. Don't leave deprecation-warning tests behind after the warning is gone.
3. Run coverage; classify each miss as *load-bearing defensive*, *feature path*, or *truly dead*. Remove the truly-dead third category.
4. Intra-file DRY pass: look for near-duplicate method pairs (e.g. `filter_`/`exclude_`, `compute`/`acompute`) and consolidate via a shared helper.
5. Cross-file DRY pass: extract patterns repeated in 3+ files (e.g. the three factory collision checks → `utils.raise_on_type_name_collision`; the three `type_name_for` classmethods → `ClassBasedTypeNameMixin`).

### Things to watch out for

- **Restoring guards after over-removal.** Removing an `if target is not None` guard that *looks* redundant can break tests that depend on the silent-skip semantic (`RelatedOrder(None, ...)` is a documented API). If a removal breaks a test, that's usually a sign the guard was load-bearing — restore it and move on.
- **Module-level caches between tests.** Any change that clears factory caches mid-run needs to use `dict.pop(key, None)` rather than `.clear()` to avoid wiping state other tests depend on. The three argument factories all have this shape.
- **Metaclass-declared class attributes.** `AdvancedFilterSet.related_filters`, `AdvancedOrderSet.related_orders`, `AdvancedAggregateSet.related_aggregates` are populated by the metaclass after `super().__new__()`. Don't read them from within `__new__` before that call — use `cls.__dict__.get("related_filters")` if you need to distinguish "this class's own" from inherited.
- **Graphene input-type lambda refs must be in closures.** `graphene.InputField(lambda tn=target_name: self.input_object_types[tn])` with a default arg captures `target_name` at *definition* time; a bare `lambda: self.input_object_types[target_name]` would close over the loop variable and resolve to the last value. Don't "simplify" this.

## Release Process

1. Bump version in three places (see "Version Bumps" above).
2. Run the full verification chain:
   ```
   uv run ruff format .
   uv run ruff check .
   uv run coverage run -m pytest
   uv run coverage report --fail-under=100
   ```
3. Write a `CHANGELOG.md` entry referencing the relevant spec docs.
4. Ship.
