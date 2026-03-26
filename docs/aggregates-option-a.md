# Option A — Built-in Connection-Level Aggregates

## Overview

The library automatically generates typed aggregate fields on the Relay connection, as a sibling to `edges` and `pageInfo`. Consumers opt in by setting `aggregate_fields` in their `AdvancedDjangoObjectType` Meta — similar to how `search_fields` works today.

The library introspects the model's field types and generates appropriate stat subfields (numeric fields get `sum`/`mean`/`stdev`; text fields get `min`/`max`/`mode`; all fields get `count`/`uniques`).

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
        # NEW: opt-in to aggregates on these fields
        aggregate_fields = ("name", "description", "created_date")
```

That's it. No additional classes to define. The library handles the rest.

### GraphQL Queries

**Basic count (no field specified):**
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

**Per-field aggregates on a text field:**
```graphql
query {
  allObjects(filter: { objectType: { name: { exact: "People" } } }) {
    aggregates {
      count
      name {
        min
        max
        mode
        uniques { value count }
      }
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
      "aggregates": {
        "count": 42,
        "name": {
          "min": "Aaron",
          "max": "Zoe",
          "mode": "John",
          "uniques": [
            { "value": "Alice", "count": 3 },
            { "value": "Bob", "count": 2 }
          ]
        }
      },
      "edges": [...]
    }
  }
}
```

**Per-field aggregates on a datetime field:**
```graphql
query {
  allObjects {
    aggregates {
      count
      createdDate {
        min
        max
      }
    }
  }
}
```

**Aggregates with filter + search + order (all work together):**
```graphql
query {
  allObjects(
    filter: { objectType: { name: { exact: "People" } } }
    search: "engineer"
    orderBy: [{ name: ASC }]
  ) {
    aggregates {
      count
      name { min max mode }
    }
    edges {
      node { name description }
    }
  }
}
```

### Value model example (numeric-like text field)
```graphql
query {
  allValues(filter: { attribute: { name: { exact: "Salary" } } }) {
    aggregates {
      count
      value { min max mode uniques { value count } }
    }
    edges {
      node { value }
    }
  }
}
```

---

## Package Changes (`django_graphene_filters`)

### New Files

#### `aggregate_types.py` — Generated GraphQL types for aggregate results

```python
# django_graphene_filters/aggregate_types.py

import graphene


class UniqueValueType(graphene.ObjectType):
    """A single unique value and its occurrence count."""
    value = graphene.String()
    count = graphene.Int()


class TextAggregateType(graphene.ObjectType):
    """Aggregate stats for text/string fields."""
    min = graphene.String()
    max = graphene.String()
    mode = graphene.String()
    uniques = graphene.List(UniqueValueType)


class NumericAggregateType(graphene.ObjectType):
    """Aggregate stats for numeric fields (Integer, Float, Decimal)."""
    min = graphene.Float()
    max = graphene.Float()
    sum = graphene.Float()
    mean = graphene.Float()
    median = graphene.Float()
    mode = graphene.Float()
    standard_deviation = graphene.Float()
    variance = graphene.Float()
    uniques = graphene.List(UniqueValueType)


class DateTimeAggregateType(graphene.ObjectType):
    """Aggregate stats for date/datetime fields."""
    min = graphene.DateTime()
    max = graphene.DateTime()
    count = graphene.Int()
```

#### `aggregate_factory.py` — Dynamically generates per-model aggregate ObjectTypes

```python
# django_graphene_filters/aggregate_factory.py

"""
Introspects a Django model + the declared aggregate_fields list,
determines each field's type, and generates a Graphene ObjectType like:

    class ObjectAggregateType(graphene.ObjectType):
        count = graphene.Int()
        name = graphene.Field(TextAggregateType)
        created_date = graphene.Field(DateTimeAggregateType)

Also provides the resolver logic that runs Django ORM .aggregate()
and Python-level stats (median, mode, stdev, etc.) on the filtered queryset.
"""
```

#### `aggregate_resolvers.py` — Computation logic

```python
# django_graphene_filters/aggregate_resolvers.py

"""
Contains the actual stats computation, split into:
- DB-level: Count, Min, Max, Sum, Avg via Django ORM .aggregate()
- Python-level: median, mode, stdev, variance, uniques via
  queryset.values_list(field, flat=True) + statistics module

The resolver receives the already-filtered queryset from
AdvancedDjangoFilterConnectionField.resolve_queryset and computes
only the stats that were actually requested in the GraphQL selection set
(to avoid unnecessary DB queries).
"""
```

### Modified Files

#### `object_type.py` — Accept `aggregate_fields` in Meta

```python
# AdvancedDjangoObjectType.__init_subclass_with_meta__
# Add aggregate_fields parameter alongside orderset_class and search_fields

@classmethod
def __init_subclass_with_meta__(
    cls,
    orderset_class=None,
    search_fields=None,
    aggregate_fields=None,  # NEW
    _meta=None,
    **options,
):
    if not _meta:
        _meta = DjangoObjectTypeOptions(cls)
    _meta.orderset_class = orderset_class
    _meta.search_fields = search_fields
    _meta.aggregate_fields = aggregate_fields  # NEW
    super().__init_subclass_with_meta__(_meta=_meta, **options)
```

#### `connection_field.py` — Generate aggregate type and resolve it

The connection field needs to:
1. Detect `aggregate_fields` from the node type Meta
2. Use `AggregateFactory` to build the aggregate ObjectType
3. Override the connection type to include an `aggregates` field
4. In `resolve_queryset`, pass the filtered queryset to the aggregate resolver

Key change in `resolve_queryset`:
```python
# After filtering is applied and before return:
# The aggregates are computed from the SAME filtered queryset as edges.
# They are attached to the connection result so the aggregates resolver
# can access them.
```

The connection type override:
```python
# Dynamically create a connection class that adds:
#   aggregates = graphene.Field(ModelAggregateType)
# This sits alongside edges and pageInfo in the response.
```

### How Aggregates Flow Through the System

```
1. Schema startup
   └─ AdvancedDjangoObjectType reads aggregate_fields from Meta
   └─ AggregateFactory introspects model fields, builds typed AggregateType
   └─ AdvancedDjangoFilterConnectionField creates custom Connection class
      with `aggregates` field

2. Query execution
   └─ resolve_queryset applies filters/search/permissions → filtered QS
   └─ Same QS is passed to both:
      ├─ Relay pagination (edges)
      └─ Aggregate resolver (inspects GraphQL selection set,
         runs only needed .aggregate() / .values_list() calls)

3. Response
   └─ { edges: [...], pageInfo: {...}, aggregates: { count: N, name: {...} } }
```

### Permissions Integration

Aggregates automatically respect permissions because they operate on the **same queryset** that `resolve_queryset` produces — which already has `get_queryset` visibility applied. No additional permission logic is needed.

However, we should consider adding `check_*_aggregate_permission` hooks for cases where a user can *see* a field but should not be able to *aggregate* it (e.g., salary data).

### Estimated Effort

- **New files:** 3 (aggregate_types.py, aggregate_factory.py, aggregate_resolvers.py)
- **Modified files:** 3 (object_type.py, connection_field.py, __init__.py)
- **Test files:** 1-2 new test modules
- **Complexity:** High — the factory that introspects model field types and generates appropriate aggregate subfields is the hardest part. The connection type override for Relay also requires care.
- **Estimated time:** 2-3 weeks

### Risks

- Relay connection type customization can be fragile with graphene-django
- Schema size grows proportionally to `aggregate_fields` × stat types
- Performance: if a query requests aggregates + edges, the DB may be hit twice (once for pagination, once for aggregation). This can be optimized with deferred resolution.
