# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--next-version-placeholder-->

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

[0.3.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.3.0
[0.2.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.2.0
[0.1.0]: https://github.com/riodw/django-graphene-filters/releases/tag/v0.1.0
