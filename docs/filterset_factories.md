Here is a focused review of `django_graphene_filters/filterset_factories.py`.

## What it does (sanity)

The flow matches upstream `graphene_django.filter.utils.get_filterset_class`, with one intentional difference: the dynamic factory path passes `filterset_base_class=AdvancedFilterSet` instead of django-filter’s default `FilterSet`, which is required for this library.

```11:38:django_graphene_filters/filterset_factories.py
def get_filterset_class(
    filterset_class: type[AdvancedFilterSet] | None,
    **meta: dict[str, Any],
) -> type[AdvancedFilterSet]:
    ...
    if filterset_class:
        graphene_filterset_class = setup_filterset(filterset_class)
    else:
        graphene_filterset_class = custom_filterset_factory(
            filterset_base_class=AdvancedFilterSet,
            **meta,
        )

    replace_csv_filters(graphene_filterset_class)

    return graphene_filterset_class
```

Upstream for comparison:

```106:117:/Users/riordenweber/projects/django-graphene-filters/.venv/lib/python3.14/site-packages/graphene_django/filter/utils.py
def get_filterset_class(filterset_class, **meta):
    ...
    if filterset_class:
        graphene_filterset_class = setup_filterset(filterset_class)
    else:
        graphene_filterset_class = custom_filterset_factory(**meta)

    replace_csv_filters(graphene_filterset_class)
    return graphene_filterset_class
```

So the local implementation is aligned with graphene-django aside from fixing the base class.

---

## Findings

### 1. Incorrect typing for `**meta` (low)

The annotation `**meta: dict[str, Any]` does not match normal variadic-kwargs typing: each *value* passed in should be typed (typically `**meta: Any`), not as `dict[str, Any]`. This is misleading for type checkers and readers.

---

### 2. Footgun: keys in `**meta` that collide with `custom_filterset_factory` (medium)

`custom_filterset_factory` is defined as:

```42:44:/Users/riordenweber/projects/django-graphene-filters/.venv/lib/python3.14/site-packages/graphene_django/filter/filterset.py
def custom_filterset_factory(model, filterset_base_class=FilterSet, **meta):
    """Create a filterset for the given model using the given meta data"""
    meta.update({"model": model})
```

This function takes `model` and `filterset_base_class` as explicit parameters. Your wrapper always passes `filterset_base_class=AdvancedFilterSet` and then `**meta`.

If `meta` ever contains `filterset_base_class`, Python raises **“multiple values for keyword argument”** when calling `custom_filterset_factory`. The same applies if `meta` duplicated `model` in a way that collided with an explicit kw—less likely with the current call shape, but `filterset_base_class` in `meta` is the realistic hazard.

Callers such as `AdvancedDjangoFilterConnectionField` merge `extra_filter_meta` into `meta` before calling `get_filterset_class` (`connection_field.py`), so a user-supplied `extra_filter_meta` that includes `filterset_base_class` would break at runtime.

---

### 3. `extra_filter_meta` can override `model` / `fields` (low–medium, behavioral)

In `connection_field.py`, `meta` is built as `{"model": ..., "fields": ...}` and then `meta.update(self._extra_filter_meta)`. Any key in `extra_filter_meta` overwrites the defaults, including **`model`** and **`fields`**. That may be intentional flexibility, but it is also a sharp edge if `extra_filter_meta` is used for unrelated options without namespacing.

---

### 4. Missing `model` when `filterset_class is None` (low)

If someone calls `get_filterset_class(None)` with no `model=` in kwargs, `custom_filterset_factory` will raise `TypeError` (missing required `model`). The connection field always supplies `model`, so normal use is fine; it is still a contract requirement worth documenting.

---

## Non-issues (checked)

- **`replace_csv_filters` mutates `base_filters` in place** — same as upstream; acceptable given how classes are produced/cached in your connection field.
- **`setup_filterset` / `GrapheneFilterSetMixin`** — unchanged from graphene-django; still the right hook for GlobalID filters.

---

## Summary

The module is small and mostly correct; the main practical risk is **keyword collisions** when `**meta` (including merged `extra_filter_meta`) contains `filterset_base_class` or overwrites `model`/`fields`. The `**meta: dict[str, Any]` annotation should be fixed for accuracy. I did not treat “must pass `model` when building from scratch” as a bug given how `AdvancedDjangoFilterConnectionField` uses it, only as API clarity.
