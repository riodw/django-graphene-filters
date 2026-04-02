## Review: `django_graphene_filters/aggregate_types.py`

### Medium: `datetime` category mixes field kinds but only exposes `DateTime`

`FIELD_CATEGORIES` maps `DateField`, `TimeField`, and `DurationField` into the same bucket (`"datetime"`), and `STAT_TYPES["datetime"]` only uses `graphene.DateTime` for `min` / `max`:

```41:44:django_graphene_filters/aggregate_types.py
    "DateTimeField": "datetime",
    "DateField": "datetime",
    "TimeField": "datetime",
    "DurationField": "datetime",
```

```76:80:django_graphene_filters/aggregate_types.py
    "datetime": {
        "count": graphene.Int,
        "min": graphene.DateTime,
        "max": graphene.DateTime,
    },
```

In practice, Django `Min`/`Max` on a `DateField` yield `date`, on `TimeField` yield `time`, and on `DurationField` yield `timedelta`. The schema always advertises `DateTime`, so clients and serialization can see **values that do not match the declared scalar** (depending on Graphene/Django’s coercion). A tighter design would split categories or map each field class to the right Graphene scalar (`Date`, `Time`, or a dedicated representation for durations).

---

### Low: `UniqueValueType.value` is always a string

```6:10:django_graphene_filters/aggregate_types.py
class UniqueValueType(graphene.ObjectType):
    """A unique value and its occurrence count."""

    value = graphene.String(description="The distinct value (as string)")
```

That matches `_uniques` in `aggregateset.py` (values are stringified). Numeric or UUID uniqueness is therefore **lossy in the API** (everything is a string). Intentional for a unified shape, but worth knowing for clients.

---

### Low: Typing of `STAT_TYPES` values

Annotations use `type | graphene.List`, but entries like `"uniques": graphene.List(UniqueValueType)` are **instances** of `List`, not the class `List`. The hint is a bit inaccurate for static analysis only; runtime is fine.

---

### Non-issues / by design

- **Only concrete field classes are listed**; anything else fails in `_get_field_category` with a clear error — reasonable boundary.
- **`VALID_STATS` derived from `STAT_TYPES`** keeps validation aligned with what the arguments factory can emit.
- **`NullBooleanField`** is legacy but still valid on older Django projects; including it is fine.

---

**Summary:** The file is small and consistent with `aggregateset.py` and `AggregateArgumentsFactory`. The one substantive gap is **Date / Time / Duration fields sharing a `DateTime`-only GraphQL shape** for `min`/`max`. Fixing that would mean finer categories or per-field scalar choice, not just tweaking this file in isolation.
