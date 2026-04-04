## Review: `django_graphene_filters/order_arguments_factory.py`

### Medium: No guard against circular `RelatedOrder` graphs

`create_order_input_type` recurses for every related field with a non-`None` `orderset`:

```61:68:django_graphene_filters/order_arguments_factory.py
        for field_name, related_order in orderset_class.get_fields().items():
            if related_order:
                sub_prefix = f"{prefix}{field_name.capitalize()}"
                target_orderset = related_order.orderset
                if target_orderset:
                    sub_type = self.create_order_input_type(target_orderset, sub_prefix)
                    fields[field_name] = graphene.InputField(sub_type)
```

If `OrderSetA` relates to `OrderSetB` and `B` relates back to `A` (or any cycle), schema build can **recurse until stack overflow**. `AggregateArgumentsFactory` uses a `_building` set to break cycles; this factory has no equivalent.

---

### Medium: Type cache collisions are silent (unlike `FilterArgumentsFactory`)

Nested types are registered only by `type_name` in `InputObjectTypeFactoryMixin.input_object_types`. There is **no** `_type_*_registry` or warning when a second, different orderset reuses the same `prefix` and would overwrite `"{prefix}OrderInputType"` (or a shared nested name). The first cached `InputObjectType` wins for that string; later factories can get the wrong shape without notice.

---

### Low: `field_name.capitalize()` is not PascalCase

```64:64:django_graphene_filters/order_arguments_factory.py
                sub_prefix = f"{prefix}{field_name.capitalize()}"
```

For a snake_case relation like `object_type`, this yields `Object_type`, not `ObjectType`. Filter-side naming often uses `pascalcase` from `stringcase`. The result is only used for **GraphQL type names**, so behavior is usually still unique and valid, but names are inconsistent and slightly harder to reason about than `ObjectType…`.

---

### Low: Related field omitted entirely when `orderset` is missing

If `related_order` is truthy but `target_orderset` is falsy, nothing is appended to `fields` for that key—no placeholder, no error. That matches the “skip” tests (`test_order_arguments_factory_target_orderset_none_skip`) but is easy to misconfigure without noticing the field disappeared from the schema.

---

### What looks solid

- **Cache check before building** (`if type_name in type(self).input_object_types`) avoids the `dict.get(key, expensive_default())` bug that exists on `FilterArgumentsFactory.arguments`.
- **`OrderDirection`** cleanly encodes normal and distinct-on ordering and lines up with `AdvancedOrderSet.get_flat_orders`.
- **Root `orderBy: [OrderInputType!]`** matches the list shape `get_flat_orders` expects.

---

**Summary:** The main risks are **infinite recursion on cyclic related ordersets** and **silent global cache collisions** for order input types when prefixes or generated names overlap. Smaller notes: `str.capitalize` for prefixes and silently dropping related fields when `orderset` is unset.
