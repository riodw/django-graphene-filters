## Review: `django_graphene_filters/filter_arguments_factory.py`

### High: `.arguments` always builds the input type (even on cache hit)

```77:82:django_graphene_filters/filter_arguments_factory.py
        input_object_type = self.input_object_types.get(
            self.filter_input_type_name,
            self.create_filter_input_type(
                self.filterset_to_trees(self.filterset_class),
            ),
        )
```

In Python, **both arguments to `dict.get()` are evaluated before `get` runs**. So `self.create_filter_input_type(...)` runs on **every** read of `.arguments`, even when `self.filter_input_type_name` is already in `input_object_types`.

Effects:

- Wasted work (full tree build + nested `create_input_object_type` calls) whenever anything touches `.arguments` more than once.
- `create_filter_input_type` **mutates** `input_object_types` and `_type_filterset_registry` each time; for the same filterset/prefix you avoid the collision warning (`prior is self.filterset_class`), but you still **construct a new** `InputObjectType` subclass and **replace** the dict entry. That can leave multiple distinct GraphQL type objects floating around if anything held an older reference.

The intended pattern is “if missing, create; else reuse”. That should be written with an explicit `if self.filter_input_type_name not in self.input_object_types: ...` (or `setdefault`), not `get(..., side_effecting_default)`.

---

### Medium: Forward references in `logic_fields` depend on mutation order

`AND` / `OR` / `NOT` use lambdas that read `self.input_object_types[self.filter_input_type_name]`. That works as long as resolution happens **after** the assignment at the end of `create_filter_input_type`. If Graphene (or tests) ever resolved those `InputField` types eagerly during `type(...)` construction **before** the outer type is registered, you could get `KeyError`. Current Graphene behavior is usually lazy enough that this is fine; it is still a coupling worth knowing.

---

### Low: `get_field` can raise on bad filter names

```168:172:django_graphene_filters/filter_arguments_factory.py
                filter_name = f"{LOOKUP_SEP}".join(
                    node.name for node in child.path if node.name != django_settings.DEFAULT_LOOKUP_EXPR
                )
                fields[child.name] = self.get_field(filter_name, all_filters[filter_name])
```

If tree construction and `get_filters()` ever disagree, `all_filters[filter_name]` is a `KeyError` at schema build time. No guard or message; acceptable as “fail fast” but brittle if filter naming edge cases appear.

---

### Low: `get_model_field` + `formfield` branch for undeclared filters

```201:205:django_graphene_filters/filter_arguments_factory.py
        if filter_type != "isnull" and name not in self.filterset_class.declared_filters:
            model_field = get_model_field(model, filter_obj.field_name)
            if hasattr(model_field, "formfield"):
                form_field = model_field.formfield(required=filter_obj.extra.get("required", False))
```

For generated filters on dotted paths (`related__field`), `filter_obj.field_name` may not be what `get_model_field` expects, depending on django-filter’s shape. Failures would surface at schema build; worth monitoring if you add exotic relations.

---

### What looks solid

- Collision detection between two **different** filtersets sharing a prefix is a good safeguard (`_type_filterset_registry` + warning).
- `filterset_to_trees` using expanded `get_filters()` matches how related filters should appear in the nested `filter` input.
- `in` / `range` → `List(...)` matches the CSV-replacement story in graphene-django.

---

**Summary:** The main issue is the **`dict.get(key, expensive_default())` anti-pattern** on `.arguments`, which defeats caching and can replace registered input types on every access. Fixing that should be a small, high-value change; the rest is mostly edge-case awareness around lazy forward refs and `get_model_field` assumptions.
