## Review: `django_graphene_filters/fieldset.py`

### High: `UnmountedType` / computed fields only come from the class body, not bases

`computed_fields` is built only from `attrs.items()` (the namespace of the class being defined):

```56:60:django_graphene_filters/fieldset.py
            computed_fields: dict[str, Any] = {}
            for attr_name, attr_value in attrs.items():
                if isinstance(attr_value, UnmountedType):
                    computed_fields[attr_name] = attr_value
```

Attributes defined on a **mixin parent** (or other base) do not appear in `attrs`, so those computed declarations are **never** copied into `_computed_fields`. That contradicts how `resolve_*` / `check_*_permission` are discovered via `dir(new_class)`, which *does* include inherited methods. A reusable mixin that only declares `display_name = graphene.String()` will not behave the same as declaring it on the concrete `AdvancedFieldSet` subclass.

---

### Medium: `_managed_fields` omits pure computed fields (no `resolve_*` / no qualifying `check_*`)

```63:66:django_graphene_filters/fieldset.py
            new_class._field_permissions = field_permissions
            new_class._field_resolvers = field_resolvers
            new_class._computed_fields = computed_fields
            new_class._managed_fields = field_permissions | field_resolvers
```

`_managed_fields` is **not** `| set(computed_fields)`. In `object_type._wrap_field_resolvers`, wrapping runs for `managed` only; computed types are injected in a separate loop. So a computed field that only has `display_name = graphene.String()` (no `resolve_display_name`, no `check_display_name_permission` synced into `_field_permissions`) gets injected into the schema but **never** gets the permission/deny-value wrapper. If you expect `check_<computed>_permission` to run, you currently need a matching model field name (so the metaclass puts it in `_field_permissions`) or a `resolve_<name>` (so it lands in `_managed_fields`). Tests always pair computed declarations with `resolve_*`.

---

### Low: `check_field` swallows every `Exception`

```102:106:django_graphene_filters/fieldset.py
        try:
            method(self.info)
            return True
        except Exception:
            return False
```

Any failure—including bugs inside `check_*_permission`—is treated as “deny”, which can hide programming errors and differs from “permission denied” semantics. This matches existing tests (e.g. `GraphQLError` → denied), but it is a broad catch.

---

### Low: Docstring mismatch at top of file

The header says `check_<field>_permission(info)`, which matches the implementation (`method(self.info)`). It also says “raises → null”; the actual behavior is “deny → `check_field` returns `False`”, then `object_type` supplies a non-null deny value for many non-nullable model fields. So “null” is not generally accurate.

---

### What looks solid

- Stripping `resolve_field` from resolver discovery is correct.
- Parsing `check_<field>_permission` only for names that exist on the model avoids accidental `check_*` helpers being treated as field guards.
- `resolve_*` discovery without model restriction matches the “computed / non-model field” story used in tests.

---

**Summary:** The main design gaps are **computed field metadata not inherited from mixins/bases** (unlike `resolve_*` / `check_*`), and **pure computed fields not entering `_managed_fields`**, which affects whether permission wrapping runs. The broad `except Exception` in `check_field` is a secondary maintainability concern.
