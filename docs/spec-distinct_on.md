# Distinct On — via `OrderDirection` enum extension

**Status:** Proposed

## Overview

Add `DISTINCT ON` support by extending the existing `OrderDirection` enum with two new values: `ASC_DISTINCT` and `DESC_DISTINCT`. No new top-level argument — distinct is expressed inline within `orderBy`.

**PostgreSQL** uses native `DISTINCT ON` for optimal performance. **All other backends** (SQLite, MySQL 8+, Oracle) use `Window(RowNumber(), partition_by=..., order_by=...)` to emulate the same behaviour. All four Django-supported backends support window functions as of Django 4.2+.

The detection is automatic via the existing `settings.IS_POSTGRESQL` flag in `conf.py`.

---

## The `OrderDirection` Enum

```python
class OrderDirection(graphene.Enum):
    ASC = "asc"
    DESC = "desc"
    ASC_DISTINCT = "asc_distinct"
    DESC_DISTINCT = "desc_distinct"
```

- `ASC` / `DESC` — standard ordering (unchanged)
- `ASC_DISTINCT` — partition by this field (distinct), sort partitions ascending
- `DESC_DISTINCT` — partition by this field (distinct), sort partitions descending

Fields marked `*_DISTINCT` define the partition. Subsequent `orderBy` entries are tie-breakers within each partition (which row survives per group). This mirrors SQL's requirement that `DISTINCT ON` fields must be the leading columns of `ORDER BY` — the array position enforces it by construction.

---

## Example Project Usage (Cookbook)

### 1. One Object per ObjectType

```graphql
query {
  allObjects(
    orderBy: [
      { objectType: { name: ASC_DISTINCT } },
      { name: ASC }
    ]
  ) {
    edges {
      node {
        name
        objectType { name }
      }
    }
  }
}
```

With 12 Objects across 3 ObjectTypes, this returns 3 rows — one per ObjectType, alphabetical by type name. Within each type, the Object with the earliest `name` alphabetically is kept.

### 2. Flat field distinct

```graphql
# One Object per unique is_private value (true/false → 2 rows max)
query {
  allObjects(
    orderBy: [
      { isPrivate: ASC_DISTINCT },
      { name: ASC }
    ]
  ) {
    edges {
      node {
        name
        isPrivate
      }
    }
  }
}
```

### 3. Combined with filter

```graphql
# One Object per ObjectType, but only non-private objects
query {
  allObjects(
    filter: { isPrivate: { exact: false } }
    orderBy: [
      { objectType: { name: ASC_DISTINCT } },
      { name: ASC }
    ]
  ) {
    edges {
      node {
        name
        objectType { name }
      }
    }
  }
}
```

### 4. Multiple distinct fields

```graphql
# One Object per unique (objectType, is_private) combination
query {
  allObjects(
    orderBy: [
      { objectType: { name: ASC_DISTINCT } },
      { isPrivate: ASC_DISTINCT },
      { name: ASC }
    ]
  ) {
    edges {
      node {
        name
        objectType { name }
        isPrivate
      }
    }
  }
}
```

### 5. Permission checks

`*_DISTINCT` directions reuse the existing `check_<field>_permission` methods on `AdvancedOrderSet`. If a user can't order by a field, they can't distinct on it either — the permission check fires before the direction is inspected.

```python
# orders.py — existing permission check applies to both ASC and ASC_DISTINCT
class ObjectTypeOrder(orders.AdvancedOrderSet):
    class Meta:
        model = models.ObjectType
        fields = "__all__"

    def check_name_permission(self, request):
        """Only staff users may order/distinct by ObjectType.name."""
        user = getattr(request, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("Staff only.")
```

---

## Package Changes (`django_graphene_filters`)

### Modified Files

#### `order_arguments_factory.py` — Extend `OrderDirection` enum

```python
class OrderDirection(graphene.Enum):
    """Enum to represent the sorting direction of a field."""

    ASC = "asc"
    DESC = "desc"
    ASC_DISTINCT = "asc_distinct"
    DESC_DISTINCT = "desc_distinct"
```

No other changes to the factory. The enum is used as the leaf type in the nested `InputObjectType` tree — existing traversal and type generation work unchanged.

#### `orderset.py` — Split `get_flat_orders` output into orders + distinct fields

The core change: `get_flat_orders` detects `*_distinct` direction values and separates them into two lists.

```python
class AdvancedOrderSet(metaclass=OrderSetMetaclass):

    def __init__(
        self,
        data: list | None = None,
        queryset: Any = None,
        request: Any = None,
    ) -> None:
        self.data = data or []
        self.qs = queryset
        self.request = request

        if self.data and self.qs is not None:
            flat_orders, distinct_fields = self.get_flat_orders(self.data)

            # Permission checks (covers both ordering and distinct fields)
            self.check_permissions(self.request, flat_orders)

            # Apply ordering
            self.qs = self.qs.order_by(*flat_orders)

            # Apply distinct if any fields were marked *_DISTINCT
            if distinct_fields:
                self.qs = self.apply_distinct(self.qs, distinct_fields, flat_orders)

    @classmethod
    def get_flat_orders(cls, order_data: list, prefix: str = "") -> tuple[list[str], list[str]]:
        """Recursively parse nested order dicts into flat ORM paths.

        Returns:
            A tuple of (flat_orders, distinct_fields).
            - flat_orders: list of ORM order strings (e.g. ["-name", "object_type__name"])
            - distinct_fields: list of ORM field paths marked as DISTINCT
              (e.g. ["object_type__name"])
        """
        flat_orders = []
        distinct_fields = []

        for order_item in order_data:
            if isinstance(order_item, Mapping):
                for key, value in order_item.items():
                    snake_key = to_snake_case(key)
                    related_orders = getattr(cls, "related_orders", {})

                    if snake_key in related_orders:
                        real_field_name = related_orders[snake_key].field_name
                        current_prefix = f"{prefix}{real_field_name}__"

                        target_orderset = related_orders[snake_key].orderset
                        if isinstance(value, Mapping) and target_orderset:
                            sub_orders, sub_distinct = target_orderset.get_flat_orders(
                                [value], current_prefix
                            )
                            flat_orders.extend(sub_orders)
                            distinct_fields.extend(sub_distinct)
                    else:
                        current_prefix = f"{prefix}{snake_key}__"

                        if isinstance(value, Mapping):
                            sub_orders, sub_distinct = cls.get_flat_orders(
                                [value], current_prefix
                            )
                            flat_orders.extend(sub_orders)
                            distinct_fields.extend(sub_distinct)
                        else:
                            # Leaf node — extract direction and distinct flag
                            direction_str = value.value if isinstance(value, enum.Enum) else str(value)
                            is_distinct = direction_str.endswith("_distinct")
                            clean_direction = direction_str.replace("_distinct", "")

                            sign = "-" if clean_direction == "desc" else ""
                            field_path = current_prefix.removesuffix("__")
                            flat_orders.append(f"{sign}{field_path}")

                            if is_distinct:
                                distinct_fields.append(field_path)

        return flat_orders, distinct_fields

    @classmethod
    def apply_distinct(
        cls,
        queryset: Any,
        distinct_fields: list[str],
        order_fields: list[str],
    ) -> Any:
        """Apply DISTINCT ON to the queryset.

        PostgreSQL: uses native .distinct(*fields).
        Other backends: uses Window(RowNumber()) to emulate.
        """
        from .conf import settings

        if settings.IS_POSTGRESQL:
            return cls._apply_distinct_postgres(queryset, distinct_fields, order_fields)
        return cls._apply_distinct_emulated(queryset, distinct_fields, order_fields)

    @staticmethod
    def _apply_distinct_postgres(queryset, distinct_fields, order_fields):
        """Native PostgreSQL DISTINCT ON.

        PostgreSQL requires that DISTINCT ON fields are the leftmost
        columns in ORDER BY. The caller (get_flat_orders) already ensures
        distinct fields come first in the flat_orders list because the user
        places them first in the orderBy array.

        We also deduplicate: if a field appears in both distinct_fields
        and the remaining order_fields, the distinct entry wins (it
        already carries the direction). This prevents invalid SQL like
        ``ORDER BY name DESC, name ASC``.
        """
        # Remove order_fields that duplicate a distinct field
        distinct_set = set(distinct_fields)
        deduped_order = [
            f for f in order_fields
            if f.lstrip("-") not in distinct_set
        ]

        # Rebuild: distinct fields lead, then remaining tiebreakers
        # Distinct fields are already in order_fields with their direction,
        # so extract them to lead the ORDER BY.
        distinct_order = [
            f for f in order_fields
            if f.lstrip("-") in distinct_set
        ]
        # If a distinct field wasn't in order_fields at all, add it bare
        seen = {f.lstrip("-") for f in distinct_order}
        for field in distinct_fields:
            if field not in seen:
                distinct_order.append(field)

        full_order = distinct_order + deduped_order
        if full_order:
            queryset = queryset.order_by(*full_order)
        return queryset.distinct(*distinct_fields)

    @staticmethod
    def _apply_distinct_emulated(queryset, distinct_fields, order_fields):
        """Emulated DISTINCT ON using Window functions.

        Works on all Django-supported backends (SQLite, MySQL 8+,
        Oracle, MariaDB 10.2+) — all set ``supports_over_clause = True``
        as of Django 4.2+.

        Django automatically wraps the window-annotated queryset in a
        subquery when ``.filter()`` is applied to a window column. This
        is transparent — no manual subquery wrapping needed.
        """
        from django.db.models import F, Window
        from django.db.models.functions import RowNumber

        partition_by = [F(field) for field in distinct_fields]

        if order_fields:
            window_order = []
            for field in order_fields:
                if field.startswith("-"):
                    window_order.append(F(field[1:]).desc())
                else:
                    window_order.append(F(field).asc())
        else:
            window_order = [F("pk").asc()]

        return (
            queryset
            .annotate(
                _distinct_row_num=Window(
                    expression=RowNumber(),
                    partition_by=partition_by,
                    order_by=window_order,
                )
            )
            .filter(_distinct_row_num=1)
        )
```

**Key change:** `get_flat_orders` now returns a `tuple[list[str], list[str]]` instead of `list[str]`. This is a **breaking change** to the return type. All callers must be updated:

- `AdvancedOrderSet.__init__` — updated above
- `AdvancedOrderSet.check_permissions` — receives `flat_orders` (unchanged, it's the same list)
- Any external code calling `get_flat_orders` directly — unlikely but possible

#### `connection_field.py` — No new arguments needed

The `orderBy` argument already exists. No `distinctOn` argument is added — distinct is expressed via the enum values within `orderBy`. The only change is that `resolve_queryset` must handle the case where `AdvancedOrderSet` applies distinct internally (which it already does — the queryset returned by `orderset.qs` is already deduplicated).

However, we need to handle the interaction with the blanket `.distinct()` call:

```python
if filterset.form.is_valid():
    qs = filterset.qs

    # Extract orderBy from args and apply orderset_class logic
    order_arg = args.get("orderBy", [])
    orderset_class = getattr(connection._meta.node._meta, "orderset_class", None)

    has_distinct_on = False
    if orderset_class and order_arg:
        orderset = orderset_class(data=order_arg, queryset=qs, request=info.context)
        qs = orderset.qs
        # Check if distinct was applied by inspecting the orderset
        has_distinct_on = bool(getattr(orderset, "_distinct_fields", []))

    # Only apply blanket .distinct() if no distinct-on was used
    # (distinct-on already guarantees uniqueness by a stronger criterion)
    if not has_distinct_on:
        qs = qs.distinct()

    # ... aggregates ...
    return qs
```

#### `conf.py` — No changes needed

`IS_POSTGRESQL` already exists.

### New Files

None. All changes are modifications to existing files.

---

## How It Flows

```
1. Schema startup
   ├─ OrderArgumentsFactory builds the orderBy InputObjectType tree
   │  └─ Leaf type is OrderDirection enum (now with 4 values instead of 2)
   └─ Schema is built normally — no new arguments

2. Query execution: orderBy: [{ objectType: { name: ASC_DISTINCT } }, { name: ASC }]
   ├─ resolve_queryset receives args with orderBy
   ├─ Filtering + search applied as normal
   ├─ AdvancedOrderSet.__init__:
   │  ├─ get_flat_orders parses the nested input:
   │  │  ├─ { objectType: { name: ASC_DISTINCT } }
   │  │  │  → flat_orders: ["object_type__name"]
   │  │  │  → distinct_fields: ["object_type__name"]
   │  │  └─ { name: ASC }
   │  │     → flat_orders: ["object_type__name", "name"]
   │  │     → distinct_fields: ["object_type__name"]
   │  ├─ check_permissions runs on flat_orders (covers both)
   │  ├─ qs.order_by("object_type__name", "name")
   │  └─ apply_distinct:
   │     ├─ PostgreSQL → .distinct("object_type__name")
   │     └─ Other → Window(RowNumber(), partition_by=[F("object_type__name")],
   │                       order_by=[F("object_type__name").asc(), F("name").asc()])
   │               .filter(_distinct_row_num=1)
   └─ Result: one row per unique object_type__name, first by name ASC

3. Response
   └─ 3 rows (one per ObjectType) instead of 12
```

---

## Edge Cases

### 1. `*_DISTINCT` without additional `orderBy` entries

Valid. The distinct field is both the partition and the sort key:

```graphql
orderBy: [{ objectType: { name: ASC_DISTINCT } }]
```

Result: one row per ObjectType, ordered by type name ascending. The "first" row per group is determined by database natural ordering (PostgreSQL) or `pk ASC` (emulated).

### 2. `*_DISTINCT` not in leading position

If the user writes:

```graphql
orderBy: [{ name: ASC }, { objectType: { name: ASC_DISTINCT } }]
```

The implementation detects that the distinct field is not leading `ORDER BY` and prepends it (PostgreSQL) or uses it as `partition_by` regardless (emulated). A warning could be logged since the user's intent is ambiguous.

### 3. Multiple `*_DISTINCT` fields

Valid — partitions by the combination of all distinct fields:

```graphql
orderBy: [
  { objectType: { name: ASC_DISTINCT } },
  { isPrivate: ASC_DISTINCT },
  { name: ASC }
]
```

Result: one row per unique `(object_type__name, is_private)` pair.

### 4. No `*_DISTINCT` in `orderBy`

Unchanged behaviour — `get_flat_orders` returns an empty `distinct_fields` list, no distinct is applied. Full backward compatibility.

### 5. Interaction with aggregates

Aggregates are computed from the filtered queryset BEFORE ordering/distinct is applied. This is already the case in `resolve_queryset`:

```
filter → aggregate (on full filtered set) → order + distinct (on display set)
```

Aggregates count all matching rows; distinct only affects pagination/display.

### 6. Interaction with `.distinct()` in `resolve_queryset`

The current code calls `qs = filterset.qs.distinct()` after filtering to remove duplicates from relationship joins. When `*_DISTINCT` is used, this blanket `.distinct()` is skipped — the distinct-on already guarantees uniqueness by a stronger criterion. See the `connection_field.py` change above.

### 7. Sub-edge connections

If `orderBy` with `*_DISTINCT` is used on a sub-edge connection (e.g. `values(orderBy: [{ value: ASC_DISTINCT }])`), the same logic applies — `AdvancedOrderSet` handles it identically regardless of nesting level.

### 8. `DESC_DISTINCT` — keep the LAST row per group

```graphql
# Latest Object per ObjectType (by name, descending)
orderBy: [
  { objectType: { name: DESC_DISTINCT } },
  { name: DESC }
]
```

With objects `["bank_aaa", "bank_zzz", "address_aaa", "address_zzz"]`, this returns `["bank_zzz", "address_zzz"]` — the last alphabetically per type.

### 9. Distinct on a field with NULL values

```graphql
# Objects have description="" (empty) or description="some text"
# NULL isn't possible (TextField default=""), but empty string IS a value
orderBy: [{ description: ASC_DISTINCT }]
```

All objects with `description=""` collapse to one row. All objects with `description="some text"` (same text) also collapse. This is correct — DISTINCT ON treats empty strings as equal.

**True NULLs** (if a model had `null=True`): PostgreSQL treats all NULLs as equal for `DISTINCT ON`. The emulated `Window(RowNumber())` also treats NULLs as one group. Behaviour is consistent.

### 10. Distinct on a boolean field — exactly 2 groups

```graphql
orderBy: [
  { isPrivate: ASC_DISTINCT },
  { name: ASC }
]
```

With 96 objects (~50% private), this returns exactly 2 rows: one with `isPrivate=false` (first alphabetically by name) and one with `isPrivate=true` (first alphabetically by name).

### 11. Distinct + filter that eliminates an entire group

```graphql
query {
  allObjects(
    filter: { isPrivate: { exact: false } }
    orderBy: [
      { objectType: { name: ASC_DISTINCT } },
      { name: ASC }
    ]
  ) { ... }
}
```

If ObjectType "bank" has 4 objects but ALL are `is_private=True`, the filter removes them all BEFORE distinct runs. Result: no "bank" row at all (not a row with empty fields). Distinct operates on the post-filter queryset.

### 12. Distinct on a RelatedOrder traversing 2+ levels

```graphql
# Values: distinct on attribute.objectType.name
# (One Value per unique ObjectType that its Attribute belongs to)
query {
  allValues(
    orderBy: [
      { attribute: { objectType: { name: ASC_DISTINCT } } },
      { value: ASC }
    ]
  ) { ... }
}
```

`get_flat_orders` recurses through `ValueOrder.attribute → AttributeOrder.object_type → ObjectTypeOrder.name`. The distinct field becomes `attribute__object_type__name`. The window function partitions by this 3-level join path.

### 13. Distinct + pagination interaction

```graphql
query {
  allObjects(
    first: 2
    orderBy: [{ objectType: { name: ASC_DISTINCT } }, { name: ASC }]
  ) {
    edges { node { name objectType { name } } }
    pageInfo { hasNextPage endCursor }
  }
}
```

With 24 ObjectTypes, distinct returns 24 rows. `first: 2` slices to 2. `hasNextPage` is `true`. Cursor-based pagination continues from the 3rd distinct row. The queryset must be stable — the emulated approach guarantees this because `RowNumber()` with a deterministic `order_by` produces stable numbering.

### 14. Distinct + search + filter + order (all four combined)

```graphql
query {
  allObjects(
    search: "bank"
    filter: { isPrivate: { exact: false } }
    orderBy: [
      { objectType: { name: ASC_DISTINCT } },
      { name: DESC }
    ]
  ) { ... }
}
```

Execution order:
1. **Search**: `icontains` across `search_fields` — narrows to objects matching "bank"
2. **Filter**: `is_private=False` — further narrows
3. **Order**: `object_type__name ASC, name DESC`
4. **Distinct**: one per `object_type__name`
5. **Pagination**: Relay slicing

If "bank" appears in multiple ObjectTypes' names/descriptions, you get one row per matching ObjectType with the last-alphabetical Object name within each.

### 15. Distinct on the same field used for ordering with opposite direction

```graphql
orderBy: [
  { name: DESC_DISTINCT },
  { name: ASC }
]
```

This is contradictory — the distinct field says DESC but the tiebreaker says ASC on the same field. The distinct direction wins (it determines partition ordering). The second entry is redundant within the partition since there's only one row per unique name. Implementation should handle this gracefully without errors — the second entry is simply ignored for the purpose of tie-breaking.

### 16. Distinct on a sub-edge connection with its own filter

```graphql
query {
  allObjects(filter: { name: { exact: "Alice" } }) {
    edges {
      node {
        name
        values(
          filter: { attribute: { name: { exact: "Email" } } }
          orderBy: [{ value: ASC_DISTINCT }]
        ) {
          edges { node { value } }
        }
      }
    }
  }
}
```

The sub-edge `values` is independently filtered and distincted. The parent `allObjects` filter has no effect on how distinct applies to the sub-edge. Each operates on its own queryset.

### 17. Empty result set after filter — distinct on nothing

```graphql
query {
  allObjects(
    filter: { name: { exact: "DOES_NOT_EXIST" } }
    orderBy: [{ objectType: { name: ASC_DISTINCT } }]
  ) { ... }
}
```

Filter returns 0 rows. Distinct on 0 rows = 0 rows. No error — the `Window` annotation on an empty queryset produces an empty queryset. PostgreSQL's `DISTINCT ON` on 0 rows also returns 0 rows.

### 18. Oracle — `ROWNUM` vs Window functions

Oracle has historically used `ROWNUM` for row limiting. Django's `Window(RowNumber())` generates standard SQL `ROW_NUMBER() OVER (...)` which Oracle 12c+ supports natively. The emulated path works on Oracle without modification. No special Oracle handling needed — Django's ORM abstracts the differences.

### 19. Distinct with `get_queryset` permission filtering (sentinel interaction)

Non-staff user queries with distinct. Some Objects have private ObjectTypes (sentinel resolution). The distinct partitioning happens on the **filtered** queryset (after `get_queryset` hides private rows). Sentinels don't appear in distinct grouping because they were already excluded at the `get_queryset` level.

However, if `apply_cascade_permissions` is NOT used and a non-private Object has a private ObjectType, the Object appears in the queryset but its `objectType` resolves to a sentinel (pk=0). Two objects with different private ObjectTypes would both have sentinel `objectType.name=""` — and distinct would collapse them into one row. This is correct behaviour: from the non-staff user's perspective, those objects all belong to "the same unknown type."

---

## Stress Test Scenarios (Cookbook)

These scenarios use the cookbook's seeded data (`seed_data(4)` → 24 ObjectTypes, 96 Objects, 171 Attributes, 684 Values, ~50% private).

### Scenario A: "Give me one example Object per Faker provider"

```graphql
query {
  allObjects(
    orderBy: [
      { objectType: { name: ASC_DISTINCT } },
      { name: ASC }
    ]
  ) {
    edges {
      node {
        name
        isPrivate
        objectType { name }
      }
    }
  }
}
```

**Expected:** 24 rows (one per ObjectType/provider). Each row is the alphabetically-first Object within that provider. Mix of `isPrivate: true/false` since distinct doesn't filter, only deduplicates.

### Scenario B: "Unique attribute names across the whole system"

```graphql
query {
  allAttributes(
    orderBy: [
      { name: ASC_DISTINCT },
      { objectType: { name: ASC } }
    ]
  ) {
    edges {
      node {
        name
        objectType { name }
      }
    }
  }
}
```

**Expected:** 171 rows (one per unique attribute name — each attribute name is unique per ObjectType in the seeded data, but if two ObjectTypes had an attribute named `name`, this would collapse them).

### Scenario C: "One Value per Attribute, most recent first"

```graphql
query {
  allValues(
    orderBy: [
      { attribute: { name: ASC_DISTINCT } },
      { value: DESC }
    ]
    first: 10
  ) {
    edges {
      node {
        value
        attribute { name }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
```

**Expected:** 10 rows (paginated). `hasNextPage: true`. Each row is a unique attribute, with the alphabetically-last value for that attribute. Cursor pagination works to fetch the remaining 161 distinct attributes.

### Scenario D: "Non-staff user — one public Object per provider"

Staff=False, so `get_queryset` filters `is_private=False`:

```graphql
query {
  allObjects(
    orderBy: [
      { objectType: { name: ASC_DISTINCT } },
      { name: ASC }
    ]
  ) {
    edges {
      node {
        name
        isPrivate
        isRedacted
        objectType { name isRedacted }
      }
    }
  }
}
```

**Expected:** Fewer than 24 rows. ObjectTypes where ALL 4 objects are private have no public objects to represent them. Every returned row has `isPrivate: false`. Some may have `objectType.isRedacted: true` if the ObjectType itself is private but the Object isn't (cascade scenario).

### Scenario E: "Distinct + filter + search + order + pagination — the kitchen sink"

```graphql
query {
  allObjects(
    search: "auto"
    filter: { isPrivate: { exact: false } }
    orderBy: [
      { objectType: { name: DESC_DISTINCT } },
      { name: ASC }
    ]
    first: 3
  ) {
    edges {
      node {
        name
        objectType { name }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
```

**Expected:** At most 3 rows. Search narrows to objects matching "auto" (hits "automotive" provider). Filter removes private ones. Distinct collapses to one per ObjectType (likely just "automotive"). Order is type name descending, then object name ascending within group. Pagination works on the deduplicated result.

---

## Design Decisions

### Why extend `OrderDirection` instead of a separate `distinctOn` argument?

1. **No new argument, no new types, no new factory** — just 2 enum values added
2. **SQL constraint enforced by construction** — distinct fields must lead `ORDER BY`, and the user naturally puts them first in the array
3. **Existing `RelatedOrder` traversal, permissions, and `get_flat_orders` all work unchanged** — the only change is detecting `*_distinct` at the leaf
4. **Consistent with the package pattern** — filters, orders, aggregates all use nested InputObjectType trees. Distinct uses the same tree, same leaf position, just a different enum value
5. **Semantically honest** — distinct-on IS an ordering concern. "Which row survives per group" requires an order. Combining them in one argument reflects this coupling

### Why `ASC_DISTINCT` / `DESC_DISTINCT` naming?

GraphQL enum values can't contain colons (`:`) or other special characters. Underscores are the standard separator. The naming reads naturally:
- `ASC_DISTINCT` → "ascending, with distinct partitioning"
- `DESC_DISTINCT` → "descending, with distinct partitioning"

### Future extensibility: `NULLS_FIRST` / `NULLS_LAST`

If nulls handling is needed later, the enum extends to at most 8 values:

```python
ASC                         # 1
DESC                        # 2
ASC_DISTINCT                # 3
DESC_DISTINCT               # 4
ASC_NULLS_FIRST             # 5
DESC_NULLS_FIRST            # 6
ASC_DISTINCT_NULLS_FIRST    # 7
DESC_DISTINCT_NULLS_FIRST   # 8
```

In practice, `NULLS_FIRST` combined with `DISTINCT` is rare, so realistically 6 values. This is not a combinatorial explosion — it's the ceiling for SQL ordering modifiers.

If the enum ever feels too large, the leaf can be changed from an enum to a small InputObjectType without breaking the nested tree structure:

```graphql
# Future (only if needed):
{ objectType: { name: { direction: ASC, distinct: true, nulls: FIRST } } }
```

But for now, 4 enum values is simple and sufficient.

### Why auto-detect PostgreSQL?

`conf.py` already detects `IS_POSTGRESQL` at startup. The emulation is functionally equivalent — same results, different SQL. The detection is a performance optimization, not a feature toggle.

---

## `get_flat_orders` Return Type Change

**This is a breaking change.** `get_flat_orders` currently returns `list[str]`. It will return `tuple[list[str], list[str]]`.

**Migration for external callers:**

```python
# Before:
flat_orders = MyOrderSet.get_flat_orders(data)

# After:
flat_orders, distinct_fields = MyOrderSet.get_flat_orders(data)
```

Since `get_flat_orders` is a classmethod on `AdvancedOrderSet` and primarily used internally, this should have minimal impact. It will be documented in the CHANGELOG as a breaking change for the 0.7.0 release.

---

## Test Plan

### Unit Tests (`tests/test_distinct.py`)

1. **`test_get_flat_orders_with_distinct`** — `ASC_DISTINCT` produces correct `flat_orders` and `distinct_fields`
2. **`test_get_flat_orders_without_distinct`** — `ASC` / `DESC` only → empty `distinct_fields`
3. **`test_get_flat_orders_mixed`** — mix of `ASC_DISTINCT` and `ASC` in one query
4. **`test_get_flat_orders_multiple_distinct`** — multiple `*_DISTINCT` fields
5. **`test_get_flat_orders_nested_distinct`** — `*_DISTINCT` on a `RelatedOrder` field
6. **`test_apply_distinct_emulated_basic`** — flat field, SQLite, returns one row per unique value
7. **`test_apply_distinct_emulated_with_order`** — flat field + ordering, correct row kept per group
8. **`test_apply_distinct_emulated_fk_field`** — FK field, partitions by FK ID
9. **`test_apply_distinct_without_order`** — no additional sort fields, uses pk fallback
10. **`test_distinct_permission_check`** — `check_<field>_permission` blocks `ASC_DISTINCT` on restricted field
11. **`test_distinct_permission_allowed`** — staff user can use `ASC_DISTINCT` on restricted field

### Integration Tests (`examples/cookbook/cookbook/recipes/tests/test_distinct.py`)

12. **`test_distinct_on_object_type`** — one Object per ObjectType via GraphQL
13. **`test_distinct_on_with_tiebreaker`** — one Object per ObjectType, tie-broken by name
14. **`test_distinct_on_with_filter`** — filter + distinct combined
15. **`test_distinct_on_flat_field`** — `ASC_DISTINCT` on `isPrivate` (returns max 2 rows)
16. **`test_distinct_on_multiple_fields`** — distinct on 2 fields
17. **`test_distinct_count_matches_unique_values`** — number of results = number of unique values in DB
18. **`test_no_distinct_returns_all`** — `ASC` / `DESC` only → all rows returned (regression)

---

## Backwards Compatibility

- Existing `orderBy` queries using `ASC` / `DESC` work exactly as before — `get_flat_orders` returns empty `distinct_fields`
- The `OrderDirection` enum gains 2 new values — additive, not breaking for clients (existing queries don't use them)
- `get_flat_orders` return type changes from `list[str]` to `tuple[list[str], list[str]]` — **breaking for direct callers** (documented in CHANGELOG)
- No new top-level GraphQL arguments — schema diff is only the 2 new enum values

---

## Database Compatibility

| Backend | Strategy | Notes |
|---------|----------|-------|
| **PostgreSQL** | Native `DISTINCT ON` | Optimal. `can_distinct_on_fields = True`. |
| **SQLite** | `Window(RowNumber())` | Full support. Django wraps window+filter in subquery automatically. |
| **MySQL 8+** | `Window(RowNumber())` | Full support. MySQL 5.7 does NOT support window functions — raises `NotSupportedError`. |
| **Oracle** | `Window(RowNumber())` | Full support. |
| **MariaDB 10.2+** | `Window(RowNumber())` | Full support. |

All four Django-supported backends set `supports_over_clause = True` as of Django 4.2+.

Django's `.distinct(*fields)` on non-PostgreSQL backends raises `NotSupportedError("DISTINCT ON fields is not supported by this database backend")`. This is why the emulated path exists — it never calls `.distinct(*fields)`, only the PostgreSQL path does.

---

## Risks

- **`get_flat_orders` return type** — breaking change from `list[str]` to `tuple[list[str], list[str]]`. Mitigated by documenting in CHANGELOG and the fact that external usage of this classmethod is unlikely.
- **MySQL 5.7 / MariaDB < 10.2** — no window function support. `Window(RowNumber())` raises `NotSupportedError`. These versions are EOL but some deployments may still use them. The error is clear and immediate — not a silent failure.
- **Performance on large tables** — emulated approach adds a window function subquery. Native PostgreSQL `DISTINCT ON` is significantly faster. Auto-detection ensures Postgres users get the optimal path.
- **Window + filter subquery wrapping** — when `.filter(_distinct_row_num=1)` is called after `.annotate(Window(...))`, Django automatically wraps the window annotation in a subquery on backends that need it. This is handled transparently by the ORM but adds one level of subquery nesting. No action needed — just be aware during debugging.
- **Interaction with blanket `.distinct()`** — `resolve_queryset` currently calls `.distinct()` after filtering. When `*_DISTINCT` is active, this must be skipped (distinct-on already guarantees uniqueness by a stronger criterion). Tested explicitly.
- **`annotate() + distinct(fields)` conflict** — Django raises `NotImplementedError` if both are combined in one query. This only affects PostgreSQL. The implementation avoids it: `_apply_distinct_postgres` uses native `DISTINCT ON` (no annotate), and `_apply_distinct_emulated` uses window functions (no `.distinct(*fields)`). The two paths never cross.
- **Edge case 15 (contradictory direction)** — `{ name: DESC_DISTINCT }` followed by `{ name: ASC }` on the same field. The distinct direction determines partition ordering; the second entry is redundant within the partition (only one row per unique name). `get_flat_orders` produces `["-name", "name"]` — Django keeps the last `order_by` for the same field. On PostgreSQL, `DISTINCT ON (name) ORDER BY name DESC, name ASC` is invalid. **Fix needed:** deduplicate `order_fields` by stripped path — if a field appears in both `distinct_fields` and regular `order_fields`, keep only the distinct entry in the ORDER BY.
- **Edge case 18 (sentinel interaction)** — Two objects with different private ObjectTypes both get sentinel `objectType.name=""` after `get_queryset`. Distinct on `object_type__name` collapses them into one. This is correct from the non-staff perspective but may surprise developers. Documented, not a bug.

---

## Estimated Effort

- **Modified files:** 2 (`orderset.py`, `order_arguments_factory.py`) + minor touch in `connection_field.py`
- **New test files:** 2 (`tests/test_distinct.py`, `examples/.../tests/test_distinct.py`)
- **Complexity:** Low — the core changes are:
  - 2 new enum values
  - ~10 lines changed in `get_flat_orders` (detect `*_distinct`, split into two lists)
  - ~40 lines for `apply_distinct` + `_apply_distinct_postgres` + `_apply_distinct_emulated`
  - Wiring in `connection_field.py` to skip blanket `.distinct()` when appropriate
