# Option C — Dynamic Field-as-Argument (DRF-Style)

## Overview

A single generic `aggregates` resolver is added to the Relay connection (or as a top-level query). The caller passes a `field` string argument at query time and receives a fixed `StatsType` object back — with nullable fields for all possible stats. Non-applicable stats (e.g., `sum` on a text field) return `null`.

This is the closest mapping to the existing DRF `StatisticsModelMixin` pattern: fully dynamic, one return type, field chosen at runtime.

---

## Example Project Usage (Cookbook)

### Schema Definition

```python
# examples/cookbook/cookbook/recipes/schema.py

class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Object
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectFilter
        orderset_class = ObjectOrder
        search_fields = ("name", "description")
        # NEW: opt-in to the dynamic aggregates resolver
        enable_aggregates = True
```

Alternatively, enable it on the connection field directly:

```python
class Query:
    all_objects = AdvancedDjangoFilterConnectionField(
        ObjectNode,
        enable_aggregates=True,
    )
```

No aggregate class to define. No field declarations. The resolver accepts any model field name at runtime.

### GraphQL Queries

**Count only (no field):**
```graphql
query {
  allObjects(filter: { objectType: { name: { exact: "People" } } }) {
    aggregates {
      count
    }
    edges {
      node { name }
    }
  }
}
```

Response:
```json
{
  "data": {
    "allObjects": {
      "aggregates": { "count": 42 },
      "edges": [...]
    }
  }
}
```

**Stats for a specific text field:**
```graphql
query {
  allObjects(filter: { objectType: { name: { exact: "People" } } }) {
    aggregates(field: "name") {
      count
      min
      max
      mode
      median
      uniques { value count }
      sum
      mean
      standardDeviation
      variance
    }
    edges {
      node { name }
    }
  }
}
```

Response (text field — numeric stats are null):
```json
{
  "data": {
    "allObjects": {
      "aggregates": {
        "count": 42,
        "min": "Aaron",
        "max": "Zoe",
        "mode": "John",
        "median": null,
        "uniques": [
          { "value": "Alice", "count": 3 },
          { "value": "Bob", "count": 2 }
        ],
        "sum": null,
        "mean": null,
        "standardDeviation": null,
        "variance": null
      },
      "edges": [...]
    }
  }
}
```

**Stats for a datetime field:**
```graphql
query {
  allObjects {
    aggregates(field: "created_date") {
      count
      min
      max
    }
    edges {
      node { name }
    }
  }
}
```

**Combined with filter + search + order:**
```graphql
query {
  allObjects(
    filter: { objectType: { name: { exact: "People" } } }
    search: "engineer"
    orderBy: [{ name: ASC }]
  ) {
    aggregates(field: "name") {
      count
      min
      max
      mode
      uniques { value count }
    }
    edges {
      node { name description }
    }
  }
}
```

**No field argument — just count:**
```graphql
query {
  allObjects(filter: { objectType: { name: { exact: "People" } } }) {
    aggregates {
      count
    }
  }
}
```

### Multi-field aggregation (workaround with aliases)

GraphQL aliases allow querying multiple fields in one request:

```graphql
query {
  allObjects {
    nameStats: aggregates(field: "name") {
      count min max mode
      uniques { value count }
    }
    dateStats: aggregates(field: "created_date") {
      min max
    }
    edges {
      node { name }
    }
  }
}
```

This works because GraphQL aliases create separate resolver invocations. Each alias runs the aggregates resolver with a different `field` argument.

---

## Package Changes (`django_graphene_filters`)

### New Files

#### `aggregate_types.py` — The single generic stats type

```python
# django_graphene_filters/aggregate_types.py

import graphene


class UniqueValueType(graphene.ObjectType):
    """A unique value and its occurrence count."""
    value = graphene.String()
    count = graphene.Int()


class StatsType(graphene.ObjectType):
    """Generic statistics result for any field.

    All fields are nullable. Non-applicable stats return null.
    For example, `sum` is null for text fields; `mode` is null
    when there's no clear mode.
    """
    count = graphene.Int(description="Total number of non-null values")
    min = graphene.String(description="Minimum value (as string)")
    max = graphene.String(description="Maximum value (as string)")
    sum = graphene.Float(description="Sum (numeric fields only)")
    mean = graphene.Float(description="Arithmetic mean (numeric fields only)")
    median = graphene.String(description="Median value")
    mode = graphene.String(description="Most frequent value")
    standard_deviation = graphene.Float(
        description="Standard deviation (numeric fields only, requires 2+ values)"
    )
    variance = graphene.Float(
        description="Variance (numeric fields only, requires 2+ values)"
    )
    uniques = graphene.List(
        UniqueValueType,
        description="Unique values with occurrence counts"
    )
```

Note: `min`, `max`, `median`, `mode` are all `String` to accommodate text, numeric, and datetime values uniformly. The caller interprets them based on context.

#### `aggregate_resolvers.py` — The computation engine

```python
# django_graphene_filters/aggregate_resolvers.py

"""
Single resolver function that:

1. Receives the filtered queryset + field name
2. Determines the Django model field type
3. Fetches values via queryset.values_list(field, flat=True)
4. Computes all applicable stats
5. Returns a dict matching StatsType fields

Uses Django ORM for count/min/max/sum/avg where possible,
falls back to Python's statistics module for median/mode/stdev/variance.

Key function:

    def compute_stats(queryset, field_name, model) -> dict:
        # 1. Validate field exists on model
        # 2. Get field type (text, numeric, datetime, boolean)
        # 3. Fetch data
        # 4. Compute stats based on field type
        # 5. Return dict with all StatsType keys (null for N/A)

Safety limits:
- Max 10,000 values fetched for Python-level stats
- uniques capped at 1,000 distinct values
- Both limits configurable via Django settings
"""
```

### Modified Files

#### `object_type.py` — Accept `enable_aggregates` in Meta

```python
@classmethod
def __init_subclass_with_meta__(
    cls,
    orderset_class=None,
    search_fields=None,
    enable_aggregates=False,  # NEW
    _meta=None,
    **options,
):
    if not _meta:
        _meta = DjangoObjectTypeOptions(cls)
    _meta.orderset_class = orderset_class
    _meta.search_fields = search_fields
    _meta.enable_aggregates = enable_aggregates  # NEW
    super().__init_subclass_with_meta__(_meta=_meta, **options)
```

#### `connection_field.py` — Add aggregates resolver to connection

```python
class AdvancedDjangoFilterConnectionField(DjangoFilterConnectionField):

    def __init__(self, type, ..., enable_aggregates=False, ...):
        self._enable_aggregates = enable_aggregates
        # ...

    @property
    def enable_aggregates(self):
        return self._enable_aggregates or getattr(
            self.node_type._meta, "enable_aggregates", False
        )

    # If enable_aggregates is True, the connection type is extended with:
    #
    #   aggregates = graphene.Field(
    #       StatsType,
    #       field=graphene.String(
    #           description="Model field name to aggregate on. "
    #                       "Omit for count-only."
    #       ),
    #   )
    #
    # The resolver:

    @classmethod
    def resolve_queryset(cls, connection, iterable, info, args, ...):
        # ... existing filter/search/order logic ...
        qs = filterset.qs.distinct()

        # Store the filtered queryset so the aggregates resolver can use it.
        # The aggregates field resolver will call compute_stats(qs, field).
        return qs

    # The aggregates field on the connection resolves lazily:
    #
    # def resolve_aggregates(root, info, field=None):
    #     qs = root.iterable  # the filtered queryset
    #     model = qs.model
    #     if field:
    #         validate_field_exists(model, field)
    #     return compute_stats(qs, field, model)
```

#### `conf.py` — Add configurable safety limits

```python
DEFAULT_SETTINGS = {
    FILTER_KEY: "filter",
    AND_KEY: "and",
    OR_KEY: "or",
    NOT_KEY: "not",
    # NEW: aggregate safety limits
    "AGGREGATE_MAX_VALUES": 10000,   # Max values fetched for Python-level stats
    "AGGREGATE_MAX_UNIQUES": 1000,   # Max unique values returned
}
```

#### `__init__.py` — Export new public API

```python
from .aggregate_types import StatsType, UniqueValueType

__all__ = [
    # ... existing exports ...
    "StatsType",
    "UniqueValueType",
]
```

### How It Flows

```
1. Schema startup
   └─ ObjectNode Meta has enable_aggregates = True
   └─ AdvancedDjangoFilterConnectionField detects enable_aggregates
   └─ Connection type is extended with:
      aggregates(field: String): StatsType

2. Query execution
   └─ resolve_queryset applies filters/search/permissions → filtered QS
   └─ Client queries aggregates(field: "name")
   └─ Aggregates resolver receives filtered QS + field name
   └─ compute_stats() validates field, determines type, computes stats
   └─ Returns StatsType with applicable fields filled, others null

3. Response
   └─ { edges: [...], pageInfo: {...}, aggregates: { count: 42, min: "Aaron", ... } }
```

### Field Validation

When the caller passes `field: "name"`, the resolver:
1. Checks that `"name"` is a concrete field on the model (using `model._meta.get_fields()`)
2. Rejects reverse relations, M2M fields, and non-existent fields with a `GraphQLError`
3. Optionally checks against an allowlist if `aggregate_fields` is set in Meta (for restricting which fields can be aggregated)

```python
# Optional allowlist (still dynamic, but restricted):
class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Object
        enable_aggregates = True
        aggregate_fields = ("name", "description", "created_date")
        # If set, only these fields can be passed as the `field` argument.
        # If not set, all concrete model fields are allowed.
```

### Permissions

Since this is dynamic, permissions are checked differently:

```python
# On the ObjectNode or a dedicated hook:
class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        enable_aggregates = True

    @classmethod
    def check_aggregate_permission(cls, info, field_name):
        """Called before computing aggregates. Raise GraphQLError to deny."""
        user = getattr(info.context, "user", None)
        if field_name == "salary" and (not user or not user.is_staff):
            raise GraphQLError("Staff only for salary aggregates.")
```

Or, the library can look for `check_<field>_aggregate_permission` methods:

```python
class ObjectNode(AdvancedDjangoObjectType):
    @classmethod
    def check_name_aggregate_permission(cls, info):
        """Only staff can aggregate on name."""
        ...
```

### The `compute_stats` Function (Core Logic)

This is essentially a Python translation of the DRF `StatisticsModelMixin`:

```python
def compute_stats(queryset, field_name, model):
    """Compute statistics for a field on a filtered queryset.

    Returns a dict matching StatsType fields.
    """
    if field_name is None:
        return {"count": queryset.count()}

    # 1. Get all non-null values
    values = list(
        queryset.exclude(**{field_name: None})
        .values_list(field_name, flat=True)
        .distinct()
    )

    if not values:
        return {"count": 0}

    data = sorted(values)
    test_val = data[0]
    can_math = isinstance(test_val, (int, float, Decimal))

    result = {
        "count": len(data),
        "min": str(min(data)),
        "max": str(max(data)),
        "sum": None,
        "mean": None,
        "median": None,
        "mode": None,
        "standard_deviation": None,
        "variance": None,
        "uniques": None,
    }

    # Mode
    try:
        result["mode"] = str(statistics.mode(data))
    except statistics.StatisticsError:
        pass

    # Median
    if len(data) > 2 and len(data) % 2 == 1:
        result["median"] = str(statistics.median(data))

    # Numeric-only stats
    if can_math:
        result["sum"] = float(sum(data))
        result["mean"] = round(float(statistics.mean(data)), 2)
        if len(data) > 1:
            result["standard_deviation"] = round(
                float(statistics.stdev(data)), 2
            )
            result["variance"] = round(
                float(statistics.variance(data)), 2
            )

    # Uniques
    counter = {}
    for item in data:
        key = str(item)
        counter[key] = counter.get(key, 0) + 1
    result["uniques"] = [
        {"value": k, "count": v}
        for k, v in sorted(counter.items())
    ][:settings.AGGREGATE_MAX_UNIQUES]

    return result
```

### Estimated Effort

- **New files:** 2 (aggregate_types.py, aggregate_resolvers.py)
- **Modified files:** 3 (object_type.py, connection_field.py, conf.py)
- **Test files:** 1 new test module
- **Complexity:** Low — no factory/metaclass/introspection needed. The stats computation is a direct port of the DRF mixin.
- **Estimated time:** 3-5 days

### Risks

- `field` is a raw string — no GraphQL schema-level validation or autocomplete
- Return type is a bag of nullable fields — caller must know which stats apply to which field types
- Single field per `aggregates` call (mitigated by aliases, but not ideal)
- `min`/`max`/`median`/`mode` are all `String` for universality, which loses type information
- Python-level stats on large datasets can be slow/memory-heavy (mitigated by safety limits)

### Advantages Over Options A and B

- Simplest implementation — no metaclasses, no factories, no per-model type generation
- Fastest to ship — can be built in under a week
- Most familiar to teams coming from DRF
- Smallest schema footprint — one `StatsType`, one `UniqueValueType`
- Easy to understand — "pass a field name, get stats back"

### Evolution Path

Option C can evolve into Option B or A over time:
1. Start with C (dynamic, fast to ship)
2. If teams need per-field type safety, add B alongside (both can coexist)
3. If full automation is desired, build A on top of B's infrastructure

The `compute_stats` function from Option C can be reused as the computation engine for Options A and B.
