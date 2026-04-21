# Remove legacy backward-compat code (1.0.0 cleanup)

**Status:** Proposed — target release: 1.0.0, folded into the class-based naming change.
**Context:** Single-consumer library. No external users rely on the legacy surface area.

## Overview

During the class-based naming migration (see
`docs/spec-base_type_naming.md`) several backward-compat shims and fallback
paths were kept to soften the transition.  Since the library has exactly
one consumer and no external release constraints, those shims are pure
dead weight — every line of "old API still works" is code that will never
be exercised and still has to be read, maintained, and covered by tests.

This document enumerates the shortcuts and spells out what to remove,
file by file, so a future session can land the cleanup in one pass.

**Rough net savings:** ~100+ lines plus one cache dict and a couple of
imports, zero loss of spec-compliant behaviour.

## Removal items

### 1. `*_input_type_prefix` kwargs — 4 sites

The spec deprecated caller-supplied prefix parameters on every public
factory/field and left them as no-ops that emit a `DeprecationWarning`.
With no downstream consumers there's no audience for the warning — delete
the kwargs outright.

**Sites:**

- `AdvancedDjangoFilterConnectionField.__init__` — `filter_input_type_prefix`,
  `order_input_type_prefix` (connection_field.py, ~L43–70).
- `FilterArgumentsFactory.__init__` — `input_type_prefix`
  (filter_arguments_factory.py, ~L67–85).
- `OrderArgumentsFactory.__init__` — `input_type_prefix`
  (order_arguments_factory.py, ~L47–63).
- `AggregateArgumentsFactory.__init__` — `input_type_prefix`
  (aggregate_arguments_factory.py, ~L39–55).

**Removal shape (example for `FilterArgumentsFactory`):**

```python
# before
def __init__(
    self,
    filterset_class: type[AdvancedFilterSet],
    input_type_prefix: str | None = None,
) -> None:
    if input_type_prefix is not None:
        warnings.warn(
            "FilterArgumentsFactory `input_type_prefix` is ignored ...",
            DeprecationWarning,
            stacklevel=2,
        )
    self.filterset_class = filterset_class
    self.filter_input_type_name = filterset_class.type_name_for()

# after
def __init__(self, filterset_class: type[AdvancedFilterSet]) -> None:
    self.filterset_class = filterset_class
    self.filter_input_type_name = filterset_class.type_name_for()
```

Apply the same shape to the other three.  Drop the `warnings` import from
any file that only used it for deprecation.

### 2. `setup_filterset` fallback path — `filterset_factories.py`

`get_filterset_class` still wraps non-`AdvancedFilterSet` classes via
graphene-django's `setup_filterset`, with a dedicated
`_setup_filterset_cache` dict for memoization.  This exists so users can
pass a plain `django_filters.FilterSet` subclass.  The library's
documented API and every example exclusively use `AdvancedFilterSet`.

**Current shape:**

```python
_setup_filterset_cache: dict[type, type[AdvancedFilterSet]] = {}

def get_filterset_class(filterset_class, **meta):
    if filterset_class:
        if isinstance(filterset_class, type) and issubclass(filterset_class, AdvancedFilterSet):
            graphene_filterset_class = filterset_class
        else:
            cached_wrapper = _setup_filterset_cache.get(filterset_class)
            if cached_wrapper is not None:
                graphene_filterset_class = cached_wrapper
            else:
                graphene_filterset_class = setup_filterset(filterset_class)
                _setup_filterset_cache[filterset_class] = graphene_filterset_class
    else:
        ... dynamic branch (keep) ...
```

**Proposed shape:**

```python
def get_filterset_class(filterset_class, **meta):
    if filterset_class is not None:
        if not (isinstance(filterset_class, type) and issubclass(filterset_class, AdvancedFilterSet)):
            raise TypeError(
                "filterset_class must subclass AdvancedFilterSet; got "
                f"{filterset_class!r}."
            )
        graphene_filterset_class = filterset_class
    else:
        ... dynamic branch (keep) ...
```

**Also drop:**
- `_setup_filterset_cache` module-level dict.
- `setup_filterset` import.
- Comment block on top of the file that justified the cache.

The dynamic branch (`filterset_class is None` → `custom_filterset_factory`)
stays — `AdvancedDjangoFilterConnectionField` still triggers it when a
node type declares `filter_fields` rather than `filterset_class`.

### 3. Mixed `RelatedFilter + Meta.fields[field]` fallback — `filter_arguments_factory.py`

`_build_input_fields` has a special case for a top-level name that is
both a `RelatedFilter` and has direct leaf lookups in `Meta.fields`
(e.g. `role = RelatedFilter(RoleFilter)` paired with
`Meta.fields = {"role": ["in"]}`).  In that case it abandons the lambda
ref and falls back to the old inline-subtree builder so the leaf lookup
(`role.in`) survives.

**Why it was added:** preserved `test_user_profile_role_o2m`'s original
filter pattern.  That test has since been rewritten to filter via the
nested `role.name` scalar, so no consumer of this branch exists.

**Proposed shape:**

```python
for root in trees:
    if root.name in self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES:
        fields[root.name] = self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES[root.name]()
        continue

    rel_filter = related_filters.get(root.name)
    if rel_filter is not None and isinstance(rel_filter, BaseRelatedFilter):
        target_fs = rel_filter.filterset
        if target_fs is not None:
            target_name = target_fs.type_name_for()
            fields[root.name] = graphene.InputField(
                lambda tn=target_name: self.input_object_types[tn],
                description=f"`{pascalcase(root.name)}` field",
            )
        continue

    fields[root.name] = self._build_path_subfield(fs_class, root, root.name)
```

**Behaviour change:** declaring `Meta.fields = {"some_fk": ["in"]}`
alongside a `RelatedFilter` on the same name will silently drop the
direct leaf lookup.  The `graphene-django` FK `__in` / `GlobalIDFilter`
limitation (documented in
`docs/fix-graphene-django-AdvancedFilterSet.md`) means this pattern
wasn't reliably useful anyway.

### 4. `AutoFilter` + `expand_auto_filter` — optional

`filters.py` ships an `AutoFilter` class (DRF-filters idiom) and
`FilterSetMetaclass.expand_auto_filter` supports it.  Not part of the
class-based naming work — this is pre-existing legacy from the
`django-rest-framework-filters` compatibility layer.

**Removal scope:**
- Delete `AutoFilter` class in `filters.py`.
- Delete `FilterSetMetaclass.expand_auto_filter` classmethod in
  `filterset.py`.
- Update `AdvancedFilterSet.get_filters` — the `isinstance(f, RelatedFilter)`
  branch is exhaustive once `AutoFilter` is gone, so the
  `expand_auto_filter` fallback path can be removed along with the
  unreachable `else` clause.
- Any tests that instantiate `AutoFilter` go with it.

**Caveat:** do this only if grepping the consuming codebase for
`AutoFilter` confirms no usage.  Lower priority than items 1–3.

## Test-layer follow-up

Removing items 1–3 invalidates a handful of tests that currently pass a
deprecated prefix kwarg or exercise the fallback branches.  Sweep each
test file for `input_type_prefix` / `filter_input_type_prefix` /
`order_input_type_prefix` literals and drop them from test call-sites.
None of those assertions carry meaning under the new surface.

Specifically expected to need updates (grep result as of the cleanup
start):

- `tests/test_filter_arguments_factory.py::test_factory_special_filter`
- `tests/test_filter_arguments_factory.py::test_get_field_model_formfield`
- `tests/test_misc_coverage.py::test_special_filter_input_type_factory`
- `tests/test_misc_coverage.py::test_get_field_with_in_lookup`
- `tests/test_misc_coverage.py::test_filter_arguments_factory_get_field_no_formfield`
- `tests/test_ordering.py::TestOrderArgumentsFactory::test_arguments_contains_order_by`

These all currently pass (they just trigger `DeprecationWarning`).
After removing the kwargs they'll TypeError on the positional arg until
the call-sites are trimmed.

## Non-goals

The following are *not* backward-compat shortcuts, even though they
resemble them — they're load-bearing spec work.  Leave alone:

- `AdvancedFilterSet` inheriting `GrapheneFilterSetMixin`.
- `type_name_for()` classmethods on all three base classes.
- BFS-based build + lambda refs in all three factories.
- `_check_collision` raising `TypeError`.
- `_dynamic_filterset_cache` in `filterset_factories.py` (memoizes the
  `filterset_class=None` auto-generation path — still needed).

## Rollout

Ship items 1–3 inside the 1.0.0 release alongside the class-based naming
changes.  Don't bother with another deprecation window — nothing out
there is consuming the deprecated surface.

Item 4 (`AutoFilter`) can ride a follow-up point release if there's any
doubt about prior usage.

## File-by-file checklist

- [ ] `django_graphene_filters/connection_field.py` — remove
      `filter_input_type_prefix` + `order_input_type_prefix` kwargs and
      warning blocks in `__init__`.
- [ ] `django_graphene_filters/filter_arguments_factory.py` — tighten
      `__init__` signature; drop `has_direct_leaf` mixed-case branch;
      drop `warnings` import if unused.
- [ ] `django_graphene_filters/order_arguments_factory.py` — tighten
      `__init__` signature; drop `warnings` import if unused.
- [ ] `django_graphene_filters/aggregate_arguments_factory.py` — tighten
      `__init__` signature; drop `warnings` import if unused.
- [ ] `django_graphene_filters/filterset_factories.py` — remove
      `_setup_filterset_cache`, `setup_filterset` import, and the
      legacy non-`AdvancedFilterSet` wrapping branch; replace with an
      explicit `TypeError`.
- [ ] (Optional) `django_graphene_filters/filters.py` +
      `django_graphene_filters/filterset.py` — remove `AutoFilter` class
      and `FilterSetMetaclass.expand_auto_filter`.
- [ ] `tests/**` — sweep for `input_type_prefix` literals and drop.
- [ ] `uv run ruff format . && uv run ruff check --fix . &&
      uv run pytest` — baseline back to green.
