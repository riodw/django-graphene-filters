# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

`django-graphene-filters` is a Python library providing advanced auto-related filters for graphene-django. It extends `django-filter` and `graphene-django` with nested/tree-structured filtering (AND/OR/NOT), related model traversal via `RelatedFilter`, ordering via `AdvancedOrderSet`, full-text search (PostgreSQL SearchVector/SearchRank/Trigram), per-field permission checks, and cascade FK visibility via `apply_cascade_permissions`.

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
uv run black .
uv run ruff check --fix .
```

**Always run both commands after making any code changes.** Line length is 110 for both black and ruff. Ruff enforces Google-style docstrings (`D`), type annotations (`ANN`), and isort (`I`) among others. Tests and examples have relaxed rules (see `pyproject.toml [tool.ruff.lint.per-file-ignores]`).

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
