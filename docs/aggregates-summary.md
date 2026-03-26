# GraphQL Aggregates — Options Summary

## Problem Statement

We need aggregate/statistics capabilities (count, sum, min, max, mean, median, mode, stdev, variance, uniques) on filtered querysets in our GraphQL API — similar to what `StatisticsModelMixin` provides in DRF.

The DRF version is fully dynamic: the caller passes `?field=salary` and gets back computed stats for that column, applied to an already-filtered queryset. GraphQL schemas are strongly typed, which creates a tension between dynamism and type safety.

This document outlines three approaches, each with different tradeoffs in complexity, type safety, and developer experience.

---

## Options at a Glance

### Option A — Built-in Connection-Level Aggregates

**Approach:** Aggregates live as a sibling to `edges` on the Relay connection, automatically generated from the model's fields. The library handles everything.

```graphql
allObjects(filter: { objectType: { name: { exact: "People" } } }) {
  edges { node { name } }
  aggregates {
    count
    name { min max mode uniques { value count } }
    createdDate { min max }
  }
}
```

**Pros:**
- Fully type-safe — each field gets only the stats that make sense for its type
- Zero boilerplate for consumers — opt in via Meta
- Aggregates respect the same filter/search/permissions as edges
- Follows patterns established by Hasura, PostGraphile, Supabase

**Cons:**
- Highest library complexity — must introspect model fields and generate typed aggregate InputObjectTypes
- Schema can become large if many fields are aggregatable
- Harder to support custom/computed aggregations

**Best for:** Teams that want a polished, batteries-included experience.

See [aggregates-option-a.md](./aggregates-option-a.md) for full details.

---

### Option B — Aggregate Mixin (Consumer Wires Up)

**Approach:** The library provides a base `AggregateSet` class (similar to `AdvancedFilterSet` / `AdvancedOrderSet`) and a mixin for the connection field. Consumers define which fields are aggregatable and what stats to expose, in their own code.

```graphql
allObjects(filter: { ... }) {
  edges { node { name } }
  aggregates {
    count
    name { min max uniques { value count } }
  }
}
```

**Pros:**
- Explicit control — consumers declare exactly which fields/stats to expose
- Moderate library complexity — library provides the machinery, not the policy
- Easy to add custom aggregation logic (e.g., weighted averages)
- Consistent with how filtersets and ordersets already work in this library

**Cons:**
- More boilerplate per model than Option A
- Consumer must understand the aggregate class API
- Risk of inconsistency across models if teams define them differently

**Best for:** Teams that want control and are comfortable with the filterset/orderset pattern.

See [aggregates-option-b.md](./aggregates-option-b.md) for full details.

---

### Option C — Dynamic Field-as-Argument (DRF-Style)

**Approach:** A single `aggregates` field (or top-level query) takes a `field` string argument and returns a generic stats object — closest to the original DRF `StatisticsModelMixin`.

```graphql
allObjects(filter: { objectType: { name: { exact: "People" } } }) {
  edges { node { name } }
  aggregates(field: "name") {
    count sum min max mean median mode
    standardDeviation variance
    uniques { value count }
  }
}
```

**Pros:**
- Simplest to implement — one return type for all models/fields
- Most dynamic — caller chooses the field at query time
- Closest mapping to the existing DRF pattern
- Smallest schema footprint

**Cons:**
- Not type-safe — `sum`/`mean`/`stdev` return `null` for string fields, caller must know
- `field` is a raw string — no autocomplete, no schema validation
- Single field at a time (or need a list argument for multi-field)
- Harder to extend with per-field custom logic

**Best for:** Teams that want a quick, pragmatic solution matching their existing DRF patterns.

See [aggregates-option-c.md](./aggregates-option-c.md) for full details.

---

## Comparison Matrix

```
                        | Option A         | Option B         | Option C
                        | (Built-in)       | (Mixin)          | (Dynamic)
------------------------|------------------|------------------|------------------
Type safety             | Full             | Full             | Partial
Schema introspection    | Full             | Full             | None (string arg)
Library complexity      | High             | Medium           | Low
Consumer boilerplate    | None             | Medium           | None
Custom aggregations     | Hard             | Easy             | Medium
Multi-field in 1 query  | Yes              | Yes              | No (1 field/call)
Schema size impact      | Large            | Medium           | Small
Pattern precedent       | Hasura/Supabase  | FilterSet/Order  | DRF Stats Mixin
```

## Shared Concerns (All Options)

1. **Permissions** — Aggregates must respect `get_queryset` visibility and `check_*_permission` methods. A non-staff user must not be able to aggregate over private rows.
2. **Performance** — Aggregation on large datasets can be expensive. Consider:
   - DB-level aggregation (`Django ORM .aggregate()`) vs Python-level (fetching all values)
   - Optional pagination/limit on `uniques`
   - Caching strategies
3. **Relay compatibility** — Aggregates should work with Relay connections without breaking pagination (`first`, `after`, `before`, `last`).
4. **Null handling** — How nulls are treated in min/max/mean etc. (Django's `aggregate()` ignores nulls by default, which is usually correct).
5. **Related field aggregation** — Should you be able to aggregate across relationships (e.g., "average value of all Values for this Object")? This is significantly more complex and could be a follow-up.

## Recommendation

Start with **Option B** if the team prefers consistency with the existing filterset/orderset pattern and wants explicit control. Start with **Option C** if speed of implementation and DRF familiarity matter most. **Option A** is the long-term ideal but has the highest upfront cost.

All three options can coexist or evolve — e.g., start with C, migrate to B, then eventually automate into A.
