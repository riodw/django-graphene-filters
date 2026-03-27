# Option B — Aggregate Mixin (Consumer Wires Up)

**Status:** Accepted — this is the approach we are implementing.

## Overview

The library provides an `AdvancedAggregateSet` base class and an `AggregateArgumentsFactory` — following the same pattern as `AdvancedFilterSet` / `AdvancedOrderSet`. Consumers define their own aggregate classes declaring which fields are aggregatable and what stats to expose. The connection field picks these up and adds the `aggregates` field to the Relay connection type.

This gives consumers explicit control over which fields and stats are exposed, while the library handles the schema generation, queryset integration, and computation.

The design is intentionally extensible: consumers can register custom stat names with arbitrary computation logic (e.g., numpy, scipy, pyomo) — the library just needs a return type mapping.

---

## Example Project Usage (Cookbook)

### 1. Define Aggregate Classes

```python
# examples/cookbook/cookbook/recipes/aggregates.py

import django_graphene_filters as aggregates
from . import models


class ObjectTypeAggregate(aggregates.AdvancedAggregateSet):
    class Meta:
        model = models.ObjectType
        # Declare fields and which stats each supports
        fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
            "description": ["count", "min", "max"],
            "created_date": ["min", "max"],
        }


class ObjectAggregate(aggregates.AdvancedAggregateSet):
    class Meta:
        model = models.Object
        fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
            "description": ["count", "min", "max"],
            "created_date": ["min", "max"],
        }

    def check_name_uniques_permission(self, request):
        """Only staff can see unique name distribution."""
        user = getattr(request, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("Staff only.")


class AttributeAggregate(aggregates.AdvancedAggregateSet):
    class Meta:
        model = models.Attribute
        fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
        }


class ValueAggregate(aggregates.AdvancedAggregateSet):
    class Meta:
        model = models.Value
        fields = {
            "value": ["count", "min", "max", "mode", "uniques"],
        }
```

### 2. Wire Up in Schema

```python
# examples/cookbook/cookbook/recipes/schema.py

from .aggregates import (
    AttributeAggregate,
    ObjectAggregate,
    ObjectTypeAggregate,
    ValueAggregate,
)

class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Object
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectFilter
        orderset_class = ObjectOrder
        search_fields = ("name", "description")
        aggregate_class = ObjectAggregate  # NEW

# OR, pass it directly to the connection field:
class Query:
    all_objects = AdvancedDjangoFilterConnectionField(
        ObjectNode,
        aggregate_class=ObjectAggregate,  # alternative location
    )
```

### 3. GraphQL Queries

**Basic count:**
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

**Field-level stats (text):**
```graphql
query {
  allObjects {
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

**Date field stats:**
```graphql
query {
  allObjects {
    aggregates {
      createdDate {
        min
        max
      }
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

### 4. Custom Aggregation Logic

Because the consumer defines the aggregate class, they can override any built-in stat computation via `compute_<field>_<stat>(self, queryset)` methods:

```python
class ObjectAggregate(aggregates.AdvancedAggregateSet):
    class Meta:
        model = models.Object
        fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
        }

    def compute_name_mode(self, queryset):
        """Custom mode computation that excludes empty strings."""
        values = list(
            queryset.exclude(name="")
            .values_list("name", flat=True)
        )
        if not values:
            return None
        return statistics.mode(values)
```

### 5. Custom Stats with External Libraries

Consumers can register entirely new stat names that don't exist in the built-in registry. The library only needs a GraphQL return type mapping via `Meta.custom_stats`:

```python
import graphene

class PortfolioAggregate(aggregates.AdvancedAggregateSet):
    class Meta:
        model = Asset
        fields = {
            "return_pct": ["count", "mean", "stdev", "sharpe_ratio"],
            "weight": ["count", "sum", "optimal_allocation"],
        }
        # Map custom stat names → GraphQL return types
        custom_stats = {
            "sharpe_ratio": graphene.Float,
            "optimal_allocation": graphene.Float,
        }

    def compute_return_pct_sharpe_ratio(self, queryset):
        """Sharpe ratio via numpy."""
        import numpy as np
        returns = np.array(
            queryset.values_list("return_pct", flat=True)
        )
        if len(returns) < 2:
            return None
        return float(np.mean(returns) / np.std(returns, ddof=1))

    def compute_weight_optimal_allocation(self, queryset):
        """Optimal allocation via Pyomo."""
        import pyomo.environ as pyo
        data = list(queryset.values_list("weight", "return_pct", "risk"))
        # ... build and solve optimization model ...
        return optimal_result
```

The resolution order for any stat is:
1. `compute_<field>_<stat>()` method on the class → **custom override** (always wins)
2. Built-in stat registry (`STAT_REGISTRY`) → **default implementation**
3. If neither exists and the stat name isn't in `custom_stats` → **configuration error at startup**

This means numpy, scipy, pyomo, or any other library can be used without the package knowing about it.

---

## Package Changes (`django_graphene_filters`)

### New Files

#### `aggregateset.py` — The `AdvancedAggregateSet` base class

This is the core module. It contains:

**`STAT_REGISTRY`** — maps built-in stat names to their computation functions:

```python
# django_graphene_filters/aggregateset.py

from django.db.models import Avg, Count, Max, Min, Sum
import statistics

STAT_REGISTRY = {
    # DB-level (single aggregate query, efficient)
    "count":    lambda qs, field: qs.values(field).distinct().count(),
    "min":      lambda qs, field: qs.aggregate(v=Min(field))["v"],
    "max":      lambda qs, field: qs.aggregate(v=Max(field))["v"],
    "sum":      lambda qs, field: qs.aggregate(v=Sum(field))["v"],
    "mean":     lambda qs, field: qs.aggregate(v=Avg(field))["v"],

    # Python-level (fetches values into memory)
    "median":   lambda qs, field: _py_median(qs, field),
    "mode":     lambda qs, field: _py_mode(qs, field),
    "stdev":    lambda qs, field: _py_stdev(qs, field),
    "variance": lambda qs, field: _py_variance(qs, field),

    # Grouped query
    "uniques":  lambda qs, field: _uniques(qs, field),
}
```

**`AggregateSetMetaclass`** — validates configuration at class creation time:

```python
class AggregateSetMetaclass(type):
    def __new__(cls, name, bases, attrs):
        new_class = super().__new__(cls, name, bases, attrs)
        meta = getattr(new_class, "Meta", None)
        if meta and hasattr(meta, "model") and hasattr(meta, "fields"):
            custom_stats = getattr(meta, "custom_stats", {})
            # 1. Validate each field exists on the model
            # 2. Determine field category (text/numeric/datetime/boolean)
            # 3. Validate each stat is compatible with the field type
            #    OR exists in custom_stats
            #    OR has a compute_<field>_<stat>() method
            # 4. Store validated config as:
            #    new_class._aggregate_config = {
            #        "name": {"category": "text", "stats": ["count", ...]},
            #        ...
            #    }
            #    new_class._custom_stats = custom_stats
        return new_class
```

**`AdvancedAggregateSet`** — the base class consumers inherit from:

```python
class AdvancedAggregateSet(metaclass=AggregateSetMetaclass):

    class Meta:
        model = None          # Django model
        fields = {}           # {field_name: [stat_names]}
        custom_stats = {}     # {stat_name: graphene_type} for non-built-in stats

    def __init__(self, queryset, request=None):
        self.queryset = queryset
        self.request = request

    def compute(self, selection_set=None):
        """Compute all requested stats.

        If selection_set is provided (from GraphQL info), only compute
        stats that were actually requested in the query — skip the rest
        for performance.

        Returns a dict like:
        {
            "count": 42,
            "name": {"min": "Aaron", "max": "Zoe", "mode": "John", ...},
            "created_date": {"min": datetime(...), "max": datetime(...)},
        }
        """
        result = {"count": self.queryset.count()}
        requested_fields = self._parse_selection_set(selection_set)

        for field_name, config in self._aggregate_config.items():
            if requested_fields and field_name not in requested_fields:
                continue

            # Permission check (field-level)
            self._check_field_permission(field_name)

            field_result = {}
            for stat_name in config["stats"]:
                if requested_fields and stat_name not in requested_fields.get(field_name, []):
                    continue

                # Permission check (stat-level)
                self._check_stat_permission(field_name, stat_name)

                # Resolution order:
                # 1. compute_<field>_<stat>() override
                # 2. STAT_REGISTRY built-in
                method = getattr(self, f"compute_{field_name}_{stat_name}", None)
                if method:
                    field_result[stat_name] = method(self.queryset)
                else:
                    field_result[stat_name] = STAT_REGISTRY[stat_name](
                        self.queryset, field_name
                    )

            result[field_name] = field_result

        return result

    def _check_field_permission(self, field_name):
        method = getattr(self, f"check_{field_name}_permission", None)
        if method:
            method(self.request)

    def _check_stat_permission(self, field_name, stat_name):
        method = getattr(self, f"check_{field_name}_{stat_name}_permission", None)
        if method:
            method(self.request)
```

**Python-level helper functions** (used by `STAT_REGISTRY`):

```python
def _fetch_values(qs, field, limit=None):
    """Fetch non-null values for a field, respecting safety limits."""
    values_qs = qs.exclude(**{field: None}).values_list(field, flat=True)
    max_values = limit or settings.AGGREGATE_MAX_VALUES
    return list(values_qs[:max_values])

def _py_median(qs, field):
    data = sorted(_fetch_values(qs, field))
    return statistics.median(data) if len(data) >= 1 else None

def _py_mode(qs, field):
    data = _fetch_values(qs, field)
    try:
        return statistics.mode(data)
    except statistics.StatisticsError:
        return None

def _py_stdev(qs, field):
    data = [float(v) for v in _fetch_values(qs, field)]
    return round(statistics.stdev(data), 2) if len(data) > 1 else None

def _py_variance(qs, field):
    data = [float(v) for v in _fetch_values(qs, field)]
    return round(statistics.variance(data), 2) if len(data) > 1 else None

def _uniques(qs, field):
    max_uniques = settings.AGGREGATE_MAX_UNIQUES
    return list(
        qs.exclude(**{field: None})
        .values(field)
        .annotate(count=Count(field))
        .order_by(field)[:max_uniques]
    )
```

#### `aggregate_arguments_factory.py` — Generates the GraphQL types

Analogous to `FilterArgumentsFactory` / `OrderArgumentsFactory`. Takes an `AdvancedAggregateSet` class and generates Graphene `ObjectType` classes for the schema.

```python
# django_graphene_filters/aggregate_arguments_factory.py

from .aggregate_types import STAT_TYPES, UniqueValueType
from .mixins import InputObjectTypeFactoryMixin


class AggregateArgumentsFactory(InputObjectTypeFactoryMixin):
    """Generates typed GraphQL ObjectTypes from an AdvancedAggregateSet."""

    def __init__(self, aggregate_class, input_type_prefix):
        self.aggregate_class = aggregate_class
        self.input_type_prefix = input_type_prefix

    def build_aggregate_type(self):
        """Build the root aggregate ObjectType.

        For an ObjectAggregate with fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
            "created_date": ["min", "max"],
        }

        Generates:
            class ObjectAggregateType(graphene.ObjectType):
                count = graphene.Int()
                name = graphene.Field(ObjectNameAggregateType)
                created_date = graphene.Field(ObjectCreatedDateAggregateType)

            class ObjectNameAggregateType(graphene.ObjectType):
                count = graphene.Int()
                min = graphene.String()
                max = graphene.String()
                mode = graphene.String()
                uniques = graphene.List(UniqueValueType)

            class ObjectCreatedDateAggregateType(graphene.ObjectType):
                min = graphene.DateTime()
                max = graphene.DateTime()
        """
        config = self.aggregate_class._aggregate_config
        custom_stats = self.aggregate_class._custom_stats
        fields = {"count": graphene.Int()}

        for field_name, field_config in config.items():
            category = field_config["category"]
            stat_names = field_config["stats"]

            # Build per-field ObjectType
            sub_fields = {}
            for stat_name in stat_names:
                if stat_name in custom_stats:
                    # Custom stat — type from Meta.custom_stats
                    sub_fields[stat_name] = custom_stats[stat_name]()
                elif stat_name in STAT_TYPES.get(category, {}):
                    # Built-in stat — type from STAT_TYPES registry
                    gql_type = STAT_TYPES[category][stat_name]
                    if callable(gql_type) and not isinstance(gql_type, type):
                        sub_fields[stat_name] = gql_type  # already instantiated (e.g. List)
                    else:
                        sub_fields[stat_name] = gql_type()
                # else: validated at metaclass time, shouldn't reach here

            sub_type_name = f"{self.input_type_prefix}{field_name.title().replace('_', '')}AggregateType"
            sub_type = self.create_input_object_type(sub_type_name, sub_fields)
            fields[field_name] = graphene.Field(sub_type)

        root_type_name = f"{self.input_type_prefix}AggregateType"
        return self.create_input_object_type(root_type_name, fields)
```

Note: We reuse `InputObjectTypeFactoryMixin` for type caching, same as the filter and order factories.

#### `aggregate_types.py` — Shared base types and type registry

```python
# django_graphene_filters/aggregate_types.py

import graphene


class UniqueValueType(graphene.ObjectType):
    """A unique value and its occurrence count."""
    value = graphene.String()
    count = graphene.Int()


# Field category classification for Django model fields:
FIELD_CATEGORIES = {
    # text
    "CharField": "text", "TextField": "text", "SlugField": "text",
    "EmailField": "text", "URLField": "text", "UUIDField": "text",
    "FilePathField": "text", "IPAddressField": "text",
    "GenericIPAddressField": "text",
    # numeric
    "IntegerField": "numeric", "SmallIntegerField": "numeric",
    "BigIntegerField": "numeric", "PositiveIntegerField": "numeric",
    "PositiveSmallIntegerField": "numeric",
    "PositiveBigIntegerField": "numeric",
    "FloatField": "numeric", "DecimalField": "numeric",
    "AutoField": "numeric", "BigAutoField": "numeric",
    "SmallAutoField": "numeric",
    # datetime
    "DateTimeField": "datetime", "DateField": "datetime",
    "TimeField": "datetime", "DurationField": "datetime",
    # boolean
    "BooleanField": "boolean", "NullBooleanField": "boolean",
}


# Mapping from stat names to graphene return types, per field category.
# Used by AggregateArgumentsFactory to generate the schema.
STAT_TYPES = {
    "text": {
        "count": graphene.Int,
        "min": graphene.String,
        "max": graphene.String,
        "mode": graphene.String,
        "uniques": graphene.List(UniqueValueType),
    },
    "numeric": {
        "count": graphene.Int,
        "min": graphene.Float,
        "max": graphene.Float,
        "sum": graphene.Float,
        "mean": graphene.Float,
        "median": graphene.Float,
        "mode": graphene.Float,
        "stdev": graphene.Float,
        "variance": graphene.Float,
        "uniques": graphene.List(UniqueValueType),
    },
    "datetime": {
        "count": graphene.Int,
        "min": graphene.DateTime,
        "max": graphene.DateTime,
    },
    "boolean": {
        "count": graphene.Int,
        "true_count": graphene.Int,
        "false_count": graphene.Int,
    },
}

# Which stats are valid for each category (used for validation):
VALID_STATS = {category: set(stats.keys()) for category, stats in STAT_TYPES.items()}
```

### Modified Files

#### `object_type.py` — Accept `aggregate_class` in Meta

Minimal change — add `aggregate_class` as a keyword parameter alongside `orderset_class` and `search_fields`:

```python
@classmethod
def __init_subclass_with_meta__(
    cls,
    orderset_class=None,
    search_fields=None,
    aggregate_class=None,  # NEW
    _meta=None,
    **options,
):
    if not _meta:
        _meta = DjangoObjectTypeOptions(cls)
    _meta.orderset_class = orderset_class
    _meta.search_fields = search_fields
    _meta.aggregate_class = aggregate_class  # NEW
    super().__init_subclass_with_meta__(_meta=_meta, **options)
```

#### `connection_field.py` — Integrate aggregate resolution

This is the most involved modification. The connection field needs to:
1. Accept `aggregate_class` (or read it from node Meta)
2. Use `AggregateArgumentsFactory` to build the aggregate `ObjectType`
3. Create a custom Relay connection class that adds `aggregates` as a sibling to `edges`
4. Compute aggregates from the **same** filtered queryset

```python
class AdvancedDjangoFilterConnectionField(DjangoFilterConnectionField):

    def __init__(self, type, ..., aggregate_class=None, ...):
        self._provided_aggregate_class = aggregate_class
        self._aggregate_class = None
        self._aggregate_type = None
        # ...

    @property
    def provided_aggregate_class(self):
        return self._provided_aggregate_class or getattr(
            self.node_type._meta, "aggregate_class", None
        )

    @property
    def aggregate_class(self):
        if not self._aggregate_class:
            self._aggregate_class = self.provided_aggregate_class
        return self._aggregate_class

    @property
    def aggregate_type(self):
        """Build (and cache) the aggregate ObjectType for this field."""
        if not self._aggregate_type and self.aggregate_class:
            from .aggregate_arguments_factory import AggregateArgumentsFactory
            prefix = self.node_type.__name__.replace("Type", "")
            factory = AggregateArgumentsFactory(self.aggregate_class, prefix)
            self._aggregate_type = factory.build_aggregate_type()
        return self._aggregate_type

    # The connection type override creates a dynamic Connection class:
    #
    #   class ObjectConnectionWithAggregates(ObjectConnection):
    #       aggregates = graphene.Field(ObjectAggregateType)
    #
    #       def resolve_aggregates(root, info):
    #           return root._aggregate_results
    #
    # This sits alongside edges and pageInfo in the response.

    @classmethod
    def resolve_queryset(cls, connection, iterable, info, args, ...):
        # ... existing filter/search/order logic ...
        qs = filterset.qs.distinct()

        # ... existing ordering logic ...

        # NEW: compute aggregates from the filtered queryset
        aggregate_class = getattr(
            connection._meta.node._meta, "aggregate_class", None
        )
        if aggregate_class:
            agg_set = aggregate_class(
                queryset=qs,
                request=info.context,
            )
            # Compute only what was requested in the selection set
            aggregate_results = agg_set.compute(
                selection_set=cls._extract_aggregate_selection(info)
            )
            # Attach to the queryset so the connection resolver can
            # pass it through to resolve_aggregates
            qs._aggregate_results = aggregate_results

        return qs
```

#### `conf.py` — Add safety limit settings

```python
DEFAULT_SETTINGS = {
    FILTER_KEY: "filter",
    AND_KEY: "and",
    OR_KEY: "or",
    NOT_KEY: "not",
    # NEW: aggregate safety limits
    "AGGREGATE_MAX_VALUES": 10000,   # Max values fetched for Python-level stats
    "AGGREGATE_MAX_UNIQUES": 1000,   # Max unique values returned in uniques list
}
```

Configurable via Django settings:
```python
# settings.py
DJANGO_GRAPHENE_FILTERS = {
    "AGGREGATE_MAX_VALUES": 50000,
    "AGGREGATE_MAX_UNIQUES": 5000,
}
```

#### `__init__.py` — Export new public API

```python
from .aggregateset import AdvancedAggregateSet

__all__ = [
    # ... existing exports ...
    "AdvancedAggregateSet",
]
```

### How It Flows

```
1. Schema startup
   ├─ AggregateSetMetaclass validates Meta.fields against the model
   │  ├─ Checks field existence, determines categories (text/numeric/datetime/boolean)
   │  ├─ Validates stat compatibility (e.g. "sum" on TextField → error)
   │  ├─ Validates custom_stats have matching compute_<field>_<stat>() methods
   │  └─ Stores validated config as _aggregate_config, _custom_stats
   ├─ Consumer defines ObjectAggregate(AdvancedAggregateSet)
   ├─ ObjectNode Meta has aggregate_class = ObjectAggregate
   ├─ AdvancedDjangoFilterConnectionField detects aggregate_class
   ├─ AggregateArgumentsFactory reads _aggregate_config + _custom_stats
   │  ├─ Builds per-field ObjectTypes (e.g. ObjectNameAggregateType)
   │  └─ Builds root ObjectAggregateType with count + per-field subfields
   └─ Connection type is extended with `aggregates` field

2. Query execution
   ├─ resolve_queryset applies filters/search/permissions → filtered QS
   ├─ AggregateSet is instantiated with filtered QS + request
   ├─ .compute() inspects GraphQL selection set
   │  ├─ Skips fields/stats not requested (performance optimization)
   │  ├─ Calls check_<field>_permission, check_<field>_<stat>_permission
   │  ├─ For each stat:
   │  │  ├─ compute_<field>_<stat>() override? → call it
   │  │  └─ else → STAT_REGISTRY[stat_name](queryset, field)
   │  └─ DB-level stats use .aggregate(), Python-level use .values_list()
   └─ Results dict attached to connection response

3. Response
   └─ { edges: [...], pageInfo: {...}, aggregates: { count: N, name: {...} } }
```

### Permission Hooks

Following the existing `check_*_permission` pattern:

```python
class ObjectAggregate(AdvancedAggregateSet):
    class Meta:
        model = models.Object
        fields = {"name": ["count", "min", "max", "uniques"]}

    def check_name_permission(self, request):
        """Block all name aggregates for non-staff."""
        ...

    def check_name_uniques_permission(self, request):
        """Block only the uniques stat for non-staff."""
        ...
```

The permission check convention:
- `check_<field>_permission(request)` — blocks ALL stats for that field
- `check_<field>_<stat>_permission(request)` — blocks a specific stat

### Performance Considerations

**DB-level stats** (`count`, `min`, `max`, `sum`, `mean`) use Django ORM `.aggregate()` — a single SQL query per stat batch. These are efficient even on large tables.

**Python-level stats** (`median`, `mode`, `stdev`, `variance`) require fetching values into memory via `.values_list()`. Safety limits prevent runaway queries:
- `AGGREGATE_MAX_VALUES` (default 10,000) — caps the number of values fetched
- If the limit is hit, the stat is computed on the truncated dataset (noted in a warning log)

**Uniques** uses a grouped `COUNT` query with `AGGREGATE_MAX_UNIQUES` (default 1,000) as a `LIMIT`.

**Selection set optimization** — `.compute()` inspects the GraphQL selection set and only computes stats that were actually requested. Querying `aggregates { count }` will not trigger any per-field stats.

### Estimated Effort

- **New files:** 3 (`aggregateset.py`, `aggregate_arguments_factory.py`, `aggregate_types.py`)
- **Modified files:** 4 (`object_type.py`, `connection_field.py`, `conf.py`, `__init__.py`)
- **Test files:** 1-2 new test modules in `tests/`, 1 in `examples/cookbook/`
- **Complexity:** Medium — the aggregate class is simpler than filtersets (no tree structure or AND/OR/NOT logic). The main work is the metaclass validation, factory schema generation, and Relay connection type extension.
- **Estimated time:** 1-2 weeks

### Implementation Plan

#### Step 1: `mixins.py` — Add `ObjectTypeFactoryMixin`

The existing `InputObjectTypeFactoryMixin` creates `graphene.InputObjectType` subclasses (for filter/order inputs). Aggregate types are **output** types (`graphene.ObjectType`), so we need a parallel mixin. Add `ObjectTypeFactoryMixin` to `mixins.py`:

```python
class ObjectTypeFactoryMixin:
    """Mixin for dynamically creating and caching Graphene ObjectTypes (output types)."""

    object_types: dict[str, type[graphene.ObjectType]] = {}

    @classmethod
    def create_object_type(
        cls,
        name: str,
        fields: dict[str, Any],
    ) -> type[graphene.ObjectType]:
        if name in cls.object_types:
            return cls.object_types[name]
        cls.object_types[name] = cast(
            type[graphene.ObjectType],
            type(name, (graphene.ObjectType,), fields),
        )
        return cls.object_types[name]
```

The `AggregateArgumentsFactory` will use this instead of `InputObjectTypeFactoryMixin`.

#### Step 2: `aggregate_types.py` — Type registry and constants

New file: `django_graphene_filters/aggregate_types.py`

Contains:
- `UniqueValueType(graphene.ObjectType)` — `value: String`, `count: Int`
- `FIELD_CATEGORIES` — maps Django field class names → category strings
- `STAT_TYPES` — maps category → {stat_name: graphene_type}
- `VALID_STATS` — derived set per category for validation

#### Step 3: `aggregateset.py` — Core aggregate class

New file: `django_graphene_filters/aggregateset.py`

Contains:
- `STAT_REGISTRY` — maps stat names → computation lambdas
- `_fetch_values()`, `_py_median()`, `_py_mode()`, `_py_stdev()`, `_py_variance()`, `_uniques()` helper functions
- `AggregateSetMetaclass` — validates `Meta.fields` against model, stores `_aggregate_config` and `_custom_stats`
- `AdvancedAggregateSet` — base class with `compute()`, `_check_field_permission()`, `_check_stat_permission()`, `_parse_selection_set()`

#### Step 4: `aggregate_arguments_factory.py` — Schema generation

New file: `django_graphene_filters/aggregate_arguments_factory.py`

Contains:
- `AggregateArgumentsFactory(ObjectTypeFactoryMixin)` — uses the **new** `ObjectTypeFactoryMixin` (not `InputObjectTypeFactoryMixin`) since aggregate types are output types
- `build_aggregate_type()` — generates root + per-field `ObjectType` classes from `_aggregate_config`

#### Step 5: `conf.py` — Safety limit settings

Add to `DEFAULT_SETTINGS`:
- `AGGREGATE_MAX_VALUES` key constant + default `10000`
- `AGGREGATE_MAX_UNIQUES` key constant + default `1000`

#### Step 6: `object_type.py` — Accept `aggregate_class` in Meta

Add `aggregate_class=None` parameter to `__init_subclass_with_meta__`, store on `_meta`.

#### Step 7: `connection_field.py` — The integration point

This is the most complex step. The connection field needs to:

**a) Override the connection type** — The connection class comes from `node_type._meta.connection` (set by graphene-django when the node type is created). We dynamically subclass it to add an `aggregates` field:

```python
# Dynamically create:
#   class ObjectNodeConnectionWithAggregates(ObjectNodeConnection):
#       aggregates = graphene.Field(ObjectAggregateType)
#
# Then override the `type` property to return this extended class.
```

The `type` property on `DjangoConnectionField` (line 94-111 of graphene_django/fields.py) returns `_type._meta.connection`. We override this to inject the aggregate field.

**b) Compute aggregates in `resolve_connection`** — After `connection_from_array_slice` creates the connection instance (line 175-187 of graphene_django/fields.py), it sets `connection.iterable = iterable`. We override `resolve_connection` to also compute and attach aggregate results:

```python
@classmethod
def resolve_connection(cls, connection, args, iterable, max_limit=None):
    result = super().resolve_connection(connection, args, iterable, max_limit)
    # iterable is the filtered queryset (attached by parent as result.iterable)
    aggregate_class = getattr(connection._meta.node._meta, "aggregate_class", None)
    if aggregate_class and hasattr(iterable, '_aggregate_results'):
        result.aggregates = iterable._aggregate_results
    return result
```

**c) Add `resolve_aggregates`** — The dynamically created connection class needs a resolver:

```python
def resolve_aggregates(root, info):
    return getattr(root, 'aggregates', None)
```

**d) Accept `aggregate_class` parameter** — In `__init__`, alongside `orderset_class`, `filter_input_type_prefix`, etc.

#### Step 8: `__init__.py` — Export `AdvancedAggregateSet`

Add to imports and `__all__`.

#### Step 9: Cookbook example

- New file: `examples/cookbook/cookbook/recipes/aggregates.py` — Define aggregate classes for all 4 models
- Modified: `examples/cookbook/cookbook/recipes/schema.py` — Add `aggregate_class` to each node's Meta

#### Step 10: Tests

- `tests/test_aggregateset.py` — Unit tests for `AdvancedAggregateSet` (metaclass validation, compute, permissions)
- `tests/test_aggregate_arguments_factory.py` — Schema generation tests
- `examples/cookbook/cookbook/recipes/tests/test_aggregates.py` — Integration tests via live GraphQL queries

### File Summary

**New files (library):**
- `django_graphene_filters/aggregate_types.py`
- `django_graphene_filters/aggregateset.py`
- `django_graphene_filters/aggregate_arguments_factory.py`

**Modified files (library):**
- `django_graphene_filters/mixins.py` — add `ObjectTypeFactoryMixin`
- `django_graphene_filters/conf.py` — add `AGGREGATE_MAX_VALUES`, `AGGREGATE_MAX_UNIQUES`
- `django_graphene_filters/object_type.py` — add `aggregate_class` param
- `django_graphene_filters/connection_field.py` — connection type override + aggregate resolution
- `django_graphene_filters/__init__.py` — export `AdvancedAggregateSet`

**New files (example):**
- `examples/cookbook/cookbook/recipes/aggregates.py`

**Modified files (example):**
- `examples/cookbook/cookbook/recipes/schema.py`

**Test files:**
- `tests/test_aggregateset.py`
- `tests/test_aggregate_arguments_factory.py`
- `examples/cookbook/cookbook/recipes/tests/test_aggregates.py` (already created)

### Risks

- Consumer must learn another class pattern (`AdvancedAggregateSet`) — mitigated by consistency with existing `FilterSet`/`OrderSet` pattern
- Connection type customization carries Relay integration risk — needs thorough testing with `graphene-django`'s connection internals
- Python-level stats on large datasets can be slow — mitigated by configurable safety limits and selection set optimization
- Custom stats with heavy computation (numpy/pyomo) could slow queries — consumer's responsibility to manage, but library should support async/deferred computation in the future

### Advantages Over Option A

- Consumer explicitly controls what's exposed (no surprise schema bloat)
- Easy to add custom computation via method overrides
- Supports custom stats with arbitrary external libraries (numpy, scipy, pyomo)
- Consistent with the project's existing FilterSet/OrderSet API philosophy
- Permissions are granular per-field and per-stat

### Advantages Over Option C

- Fully type-safe — each field's stats have correct GraphQL types
- Schema introspection works — clients get autocomplete for available stats
- Multi-field aggregates in a single query (no aliases needed)
- Compile-time validation — invalid field/stat combos are caught at schema startup, not at query time
- Custom stats are first-class citizens with typed return values
