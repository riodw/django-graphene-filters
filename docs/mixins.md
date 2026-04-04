## Review: `django_graphene_filters/mixins.py`

### Medium: `get_concrete_field_names` uses `column` as a proxy for “concrete”

```10:15:django_graphene_filters/mixins.py
def get_concrete_field_names(model: type[models.Model]) -> list[str]:
    ...
    return [f.name for f in model._meta.get_fields() if hasattr(f, "column")]
```

In Django, “has a `column` attribute” is usually aligned with DB-backed fields, but it is not the same as `field.concrete` / “appears in `Model._meta.concrete_fields`”. Edge cases (custom fields, future Django internals, or unusual `Field` subclasses) could be included or excluded differently than you intend. If this list is used for security or discovery (fieldset permissions, orderset field lists), tightening to an explicit check (e.g. `getattr(f, "concrete", False)` and/or `not f.many_to_many` where appropriate) would be clearer and more stable.

---

### Medium: `InputObjectTypeFactoryMixin` cache is global for every user of the mixin (except overrides)

```49:49:django_graphene_filters/mixins.py
    input_object_types: dict[str, type[graphene.InputObjectType]] = {}
```

`create_input_object_type` keys only by `name`. Any subclass that does **not** shadow `input_object_types` shares this single dict (e.g. `OrderArgumentsFactory`). Two unrelated ordersets that happen to produce the same nested type name will share the **first** registered shape; the second is ignored (cache hit returns the old type). `FilterArgumentsFactory` defines its own `input_object_types` to avoid sharing with filters, but **order** types can still collide with each other across the app.

Same structural risk as discussed for `ObjectTypeFactoryMixin` / aggregates: **name alone is not a safe cache key** if different schemas reuse the same string.

---

### Low: `ObjectTypeFactoryMixin` — same name-based cache semantics

```82:105:django_graphene_filters/mixins.py
    object_types: dict[str, type[graphene.ObjectType]] = {}
```

Identical tradeoff for aggregate output types: correct when prefixes are unique, wrong if two aggregate graphs share a generated `...AggregateType` name with different fields.

---

### Low: `LazyRelatedClassMixin.resolve_lazy_class` and import errors

```31:40:django_graphene_filters/mixins.py
        if isinstance(class_ref, str):
            try:
                return import_string(class_ref)
            except ImportError:
                if bound_class:
                    path = ".".join([bound_class.__module__, class_ref])
                    return import_string(path)
                raise
```

- Any `ImportError` from the absolute path triggers the relative fallback, not only “no such module”. A typo in a valid package path could incorrectly fall through to `bound_class.__module__ + "." + class_ref` and raise a confusing second error.
- `callable(class_ref) and not isinstance(class_ref, type)` treats **instances** with `__call__` like factories; that is usually fine but worth knowing.

---

### Low: No thread-safety on caches

The dicts are mutated at schema-build time without locking. Typical Django is single-threaded for schema setup; concurrent schema builds (unusual) could race.

---

### What looks solid

- `LazyRelatedClassMixin` cleanly covers string paths, same-module short names, and zero-arg callables for lazy resolution.
- The factory mixins keep Graphene type explosion under control and match how the rest of the library builds dynamic types.

---

**Summary:** The actionable issues are **`get_concrete_field_names` heuristics** (prefer explicit “concrete field” rules) and **global type caches keyed only by name** (collision risk across orders / aggregates unless prefixes are guaranteed unique). The lazy-import fallback is slightly blunt but acceptable for typical circular-import use cases.
