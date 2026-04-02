## Review: `django_graphene_filters/aggregate_arguments_factory.py`

### High: Root `count` vs model field named `count`

The root aggregate type always defines a total-row `count`, then fills in one GraphQL field per entry in `_aggregate_config`:

```69:86:django_graphene_filters/aggregate_arguments_factory.py
        root_fields: dict[str, graphene.Field | graphene.Scalar] = {
            "count": graphene.Int(description="Total number of records in the filtered result set"),
        }

        for field_name, field_config in config.items():
            category = field_config["category"]
            stat_names = field_config["stats"]

            # Build per-field sub-type
            sub_fields = self._build_stat_fields(category, stat_names, custom_stats)
            sub_type_name = f"{self.input_type_prefix}{pascalcase(field_name)}AggregateType"
            sub_type = self.create_object_type(sub_type_name, sub_fields)

            root_fields[field_name] = graphene.Field(
                sub_type,
                description=f"Aggregate statistics for `{field_name}`",
            )
```

If `Meta.fields` includes a Django field whose name is literally `count`, the loop sets `root_fields["count"]` to the per-field aggregate `Field` and **replaces** the root total-count scalar. The GraphQL shape no longer matches what `AdvancedAggregateSet.compute()` builds (`compute()` also seeds `result["count"]` as the total, then can overwrite it when it processes a field named `count`). So naming a modeled field `count` is unsafe end-to-end; the factory should detect/reserve that name (or use a prefixed root field).

---

### Medium: Name clash between a stat field and a `RelatedAggregate` attribute

Configured stats use `field_name` from `Meta.fields`. Nested aggregates use `rel_name` (the class attribute name). If the same string appears in both (e.g. a model field `values` and `values = RelatedAggregate(...)`), the **related block runs second** and **overwrites** the stat subtree field:

```88:102:django_graphene_filters/aggregate_arguments_factory.py
        ...
        try:
            for rel_name, rel_agg in getattr(self.aggregate_class, "related_aggregates", {}).items():
                ...
                root_fields[rel_name] = graphene.Field(
                    child_type,
                    description=f"Aggregates across `{rel_name}` relationship",
                )
```

That yields a schema that does not reflect the metaclass config. There is no validation that `rel_name` is disjoint from `_aggregate_config` keys.

---

### Medium: Global type cache can serve the wrong shape

Subtypes are created via `ObjectTypeFactoryMixin.create_object_type`, keyed only by the generated **string name**:

```82:105:django_graphene_filters/mixins.py
    object_types: dict[str, type[graphene.ObjectType]] = {}

    @classmethod
    def create_object_type(
        cls,
        name: str,
        fields: dict[str, Any],
    ) -> type[graphene.ObjectType]:
        ...
        if name in cls.object_types:
            return cls.object_types[name]
```

If two different aggregate setups ever produce the same `sub_type_name` / `root_type_name` (same `input_type_prefix` + `pascalcase(field_name)` + `AggregateType` suffix) but **different** `fields` dicts, the second caller gets the **cached** type and wrong fields. Prefixes are usually `NodeName + AggregateClassName`, so collisions are unlikely but not impossible if names are reused deliberately or `pascalcase` maps two field names to the same token.

---

### Low: Cycle handling drops the back-edge field

While building, `target_class in _building` causes the related branch to `continue`, so **no `Field` is added** for that edge. That avoids infinite recursion (see tests) but means **cycles are represented by omitting one of the relations** in the schema, not by a stub or lazy type. Worth documenting so users are not surprised.

---

### Low: `_building` is a process-global class set

```19:21:django_graphene_filters/aggregate_arguments_factory.py
    _building: set[type] = set()
```

It is not keyed by task/thread. In practice schema build is usually single-threaded; concurrent schema generation could theoretically interleave entries in `_building` (low risk for most deployments).

---

### Low: Custom stats typed as list/complex Graphene types

For built-in stats, `List` types are wrapped in `graphene.Field(gql_type, ...)`. The `custom_stats` branch always does `gql_type(description=...)`. If a custom stat is an instantiated `graphene.List(...)` (or another wrapped type), you may need the same `Field(...)` pattern as the built-in branch to match Graphene’s expectations.

---

## What looks solid

- Match with `STAT_TYPES` / per-category stats and skipping unknown stat names in `_build_stat_fields` is consistent with “schema only exposes known typings,” and your tests cover the skip path.
- Using `pascalcase` for stable GraphQL-ish names is coherent with the rest of the codebase.
- Try/finally around `_building` correctly pairs add/discard for non-circular recursion.

---

**Summary:** The main correctness issues are **reserved root name `count`** colliding with a real model field name, and **key collisions** between `Meta.fields` and `RelatedAggregate` attribute names. The global `object_types` cache is a secondary risk if type names ever collide. I can suggest concrete fixes (reserved names, metaclass validation, cache key by fields hash) if you want to implement them next.
