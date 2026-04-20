# Class-Based GraphQL Type Naming (1.0.0)

**Status:** Proposed — target release: 1.0.0 (breaking change).

## Overview

Rename every auto-generated GraphQL type in the library — filter input types, order input types, aggregate output types — so that the name is derived from the consumer's declared class (`AdvancedFilterSet` / `AdvancedOrderSet` / `AdvancedAggregateSet`) rather than from the path the schema generator took to reach it.

Today the same logical type — e.g. `BrandFilter.name` with an `exact` lookup — materialises under a different GraphQL type name depending on which root query reaches it:

| Query path | Generated type name today |
| --- | --- |
| `tools(filter: { brand: { name: { exact: … } } })` | `ToolToolFilterBrandNameFilterInputType` |
| `toolMetrics(filter: { tool: { brand: { name: { exact: … } } } })` | `ToolMetricToolMetricFilterToolBrandNameFilterInputType` |

The shapes are identical. The names aren't. That forces every frontend that caches introspection (our own `Home3.vue` + Pinia schema cache; Apollo in-memory cache; any generated client) to refetch and re-store the same tree per root.

After this change both queries reference `BrandFilterInputType` (and `BrandFilterNameFilterInputType` for the operator bag on `name`). Apollo's name-keyed cache dedupes them. A persistent cross-page Pinia schema store becomes viable without cache explosion.

> This is a schema rename — every client that hard-codes type names breaks. It's the right time to do it: the library has not released 1.0 yet, and the cross-page query-state work (see `spec-cross_page_introspection_query_state.md`) motivates the change.

---

## Scope — what the fix applies to

The user-facing dynamic frontend introspects **four** concerns via GraphQL:

1. **Filters** → `FilterArgumentsFactory` — broken. Fix here.
2. **Ordering** → `OrderArgumentsFactory` — broken. Fix here.
3. **Aggregates** → `AggregateArgumentsFactory` — broken. Fix here.
4. **Columns** → plain `DjangoObjectType` node classes — **already stable** (names come from the consumer's `Node` subclass, e.g. `ObjectNode`). No action required.

In addition:

- Static input types in `input_types.py` (`SearchConfigInputType`, `SearchVectorInputType`, `SearchQueryInputType`, `SearchRankFilterInputType`, `TrigramFilterInputType`, `FloatLookupsInputType`, etc.) are already globally named. **No action required.**
- Connection / Edge types are named by graphene-django from the node class. **No action required.**

Every other auto-named GraphQL type in this library gets renamed.

---

## Current state — audit

Every type-name construction site the change must touch:

### `filter_arguments_factory.py`

- L65 — root: `f"{self.input_type_prefix}FilterInputType"`
- L173 — recursion prefix: `prefix + pascalcase(root.name)`
- L178 — subtree: `f"{prefix}{pascalcase(root.name)}FilterInputType"`

### `order_arguments_factory.py`

- L40 — root: `f"{self.input_type_prefix}OrderInputType"`
- L59 — per-call: `f"{prefix}OrderInputType"`
- L76 — recursion prefix: `f"{prefix}{pascalcase(field_name)}"`

### `aggregate_arguments_factory.py`

- L80 — per-field sub-type: `f"{self.input_type_prefix}{pascalcase(field_name)}AggregateType"`
- L101 — per-related child prefix: `f"{self.input_type_prefix}{pascalcase(rel_name)}"`
- L111 — root: `f"{self.input_type_prefix}AggregateType"`

### Prefix seed sites (feed the factories)

- `connection_field.py` L93–94 (aggregate), L114–117 (order), L179–182 (filter): each builds `f"{node_type_name}{class.__name__}"`.
- `object_type.py` L51–52: same shape, for nested/sub-edge aggregate injection.

**Pattern**: every seed is `{NodeName}{ClassName}`, and every factory then appends path segments. This guarantees duplication even when two consumers use the same FilterSet/OrderSet/AggregateSet on different nodes.

---

## Naming scheme — the fix

Each auto-generated type's name is derived from the **declaring class name** alone. No node prefix. No traversal path.

### Filters

| Type | New name | Old name (example) |
| --- | --- | --- |
| FilterSet root | `{FilterSetClassName}InputType` | `ToolToolFilterFilterInputType` → `ToolFilterInputType` |
| Per-field operator bag | `{FilterSetClassName}{FieldName}FilterInputType` | `ToolToolFilterBrandNameFilterInputType` → `BrandFilterNameFilterInputType` |
| `RelatedFilter` subfield | *(reference to the target filterset's root type via `lambda`)* | n/a |

So `ObjectFilter.name` — a CharField with `__all__` lookups — always becomes `ObjectFilterNameFilterInputType`, regardless of whether it's reached directly (`allObjects(filter: { name: … })`) or through a relation (`allValues(filter: { object: { name: … } })`).

Each `RelatedFilter` traversal emits a `graphene.InputField(lambda: self.input_object_types["{TargetFilterSet}InputType"])` reference rather than a newly-named inline subtree — this mirrors the pattern already used for `and` / `or` / `not` in [filter_arguments_factory.py:124-133](../django_graphene_filters/filter_arguments_factory.py).

### Orders

| Type | New name |
| --- | --- |
| OrderSet root | `{OrderSetClassName}InputType` |
| `RelatedOrder` subfield | *(reference to target orderset's root type)* |

`OrderDirection` enum stays global (it's already shared — defined once in `order_arguments_factory.py`).

### Aggregates

| Type | New name |
| --- | --- |
| AggregateSet root | `{AggregateSetClassName}Type` |
| Per-field stat bag | `{AggregateSetClassName}{FieldName}Type` |
| `RelatedAggregate` subfield | *(reference to target aggregateset's root type)* |

`UniqueValueType` (in `aggregate_types.py`) is already globally named.

---

## Shape invariant (why names can safely be stable)

A filter/order/aggregate set's shape is fully determined by its class declaration:

- A `FilterSet`'s `Meta.fields` + `declared_filters` define its operator bag per field — deterministic.
- An `OrderSet`'s `Meta.fields` define its orderable fields — deterministic.
- An `AggregateSet`'s `Meta.fields` + `custom_stats` define its stat bag per field — deterministic.

Two consumers who want **different** shapes on what conceptually is "the same entity" must declare different classes. This is the same discipline as naming Django models or DRF serializers — and it's exactly the reason Apollo can safely key its schema cache by type name on the client.

If a consumer declares `AttributeFilter.name = ["exact", "icontains"]` and `BrandFilter.name = ["exact"]`, the two emit `AttributeFilterNameFilterInputType` and `BrandFilterNameFilterInputType` — distinct, non-colliding, no data loss.

---

## Class-name collision handling

Two filtersets with the same `__name__` coming from different modules (e.g. `app_a.filters.BrandFilter` vs `app_b.filters.BrandFilter`) must not silently collide.

The existing collision warning in `FilterArgumentsFactory.arguments` already catches this pattern. We preserve and extend it to cover all three factories:

1. On type creation, register `(type_name, declaring_class)` in a factory-level registry.
2. On a second creation attempt with the same `type_name` but a different class, **raise** (not warn). Under class-based naming a collision is a bug, not a user-input issue: either two modules declared `BrandFilter` without distinguishing them or the schema is being built twice with stale caches.
3. Offer a `meta.type_name_override: str` escape hatch on each set class for the rare case a consumer really wants two independently-named sets with the same short class name.

This is stricter than today (path-based naming swept collisions under the rug by making the names different). That's intentional — the whole point of this change is identity by name.

---

## Migration strategy — 1.0.0 breaking change

No opt-in flag. No dual-naming mode. Just ship it under 1.0.0 and document the rename.

Rationale:

- The library has not released 1.0 yet.
- A dual-naming mode doubles the schema, defeats Apollo's cache (which is the whole point), and leaves two code paths to maintain forever.
- Existing consumers need to regenerate any generated clients after the bump. The schema is self-describing; clients recompile from the current SDL.

### Deprecations

Three connection-field constructor params become vestigial:

- `filter_input_type_prefix` — no longer influences naming, but keep as documented no-op for one minor version, then remove in 1.1.
- `order_input_type_prefix` — same.
- There is no `aggregate_input_type_prefix` today.

Passing either param emits a `DeprecationWarning`.

### Changelog entry (draft)

> **1.0.0 — breaking**: GraphQL input/output types generated by `FilterArgumentsFactory`, `OrderArgumentsFactory`, and `AggregateArgumentsFactory` are now named after the declaring `AdvancedFilterSet` / `AdvancedOrderSet` / `AdvancedAggregateSet` class, not the traversal path. E.g. `ToolToolFilterBrandNameFilterInputType` → `BrandFilterNameFilterInputType`. If you hard-code type names in a generated client, regenerate. See `docs/spec-base_type_naming.md`.

---

## Implementation plan

1. **Add a helper on each base class** — `AdvancedFilterSet.type_name_for(field_name: str | None = None) -> str`, and symmetric helpers on `AdvancedOrderSet` / `AdvancedAggregateSet`. Defaults to `f"{cls.__name__}FilterInputType"` (or the equivalent per-kind suffix). Honours an optional `Meta.type_name_override` / `Meta.type_name_prefix` escape hatch.
2. **Rewrite each factory** to call the helper instead of building names from a prefix + path:
   - `FilterArgumentsFactory.create_filter_input_subfield` — detect `RelatedFilter` boundaries by cross-referencing the current tree node against `self.filterset_class.related_filters`. **This matters**: `filterset_to_trees()` flattens expanded paths (`brand__name__exact` becomes a linear chain of `Node`s), so the tree structure alone can't tell you which nodes are relation hops. When a top-level tree node's name matches a key in `related_filters`, emit `graphene.InputField(lambda: self.input_object_types[target_cls.type_name_for()])` targeting the related filterset's root type — same lambda pattern used today for `and`/`or`/`not`. Do not recurse into an inline subtree for that branch.
   - `OrderArgumentsFactory.create_order_input_type` — simpler because `orderset_class.get_fields()` already surfaces `RelatedOrder` entries explicitly. Replace the inline recursive build with a lambda reference to the target orderset's root type. The existing `_building` cycle guard becomes redundant and can be dropped (lambda-resolution-at-call-time handles cycles the same way `SearchQueryInputType` resolves its own `and`/`or`/`not` fields).
   - `AggregateArgumentsFactory.build_aggregate_type` — already iterates `cls.related_aggregates` explicitly; switch the child-factory construction to pass no prefix (target class supplies the name) and consider replacing the inline build with a lambda-ref `graphene.Field(lambda: self.object_types[target_cls.type_name_for()])` for symmetry. The `_building` guard can likewise retire.
3. **Drop the `{node_type_name}{class.__name__}` prefix seeds** in `connection_field.py` and `object_type.py`. The factories no longer accept a prefix at all; they derive from the bound class.
4. **Tighten collision detection** — see above. Registry lives on each factory class.
5. **Update tests** — every test that asserts a generated type name must be updated. Grep `FilterInputType`, `OrderInputType`, `AggregateType` in `examples/**` and any test fixtures.
6. **Remove / deprecate the `*_input_type_prefix` params** on `AdvancedDjangoFilterConnectionField`. Emit `DeprecationWarning` if passed.
7. **Memoize dynamic FilterSet generation** in `filterset_factories.get_filterset_class`. Today `custom_filterset_factory` fabricates a new `AdvancedFilterSet` subclass on every call — two connection fields on the same model (without an explicit `filterset_class`) end up with two distinct classes sharing the same `__name__`, which would trip the class-based naming's collision check. Cache by `(model, frozenset(fields.items()))` so identical configs return the same class object.

---

## TODO index — where each change is tagged in the code

Every pending change is flagged inline with `# TODO(spec-base_type_naming.md)`. Grep for `TODO\(spec-base_type_naming` to enumerate from the repo root.

| File | Tag | What the TODO marks |
| --- | --- | --- |
| `filter_arguments_factory.py` | `__init__` | Drop `input_type_prefix` param; derive `filter_input_type_name` from `filterset_class.__name__`. |
| `filter_arguments_factory.py` | `create_filter_input_subfield` | Drop prefix accumulation; detect `RelatedFilter` nodes via `self.filterset_class.related_filters` and emit lambda refs instead of inline subtrees. |
| `order_arguments_factory.py` | `__init__` | Drop `input_type_prefix` param; derive `order_input_type_name` from `orderset_class.__name__`. |
| `order_arguments_factory.py` | `create_order_input_type` | Class-based `type_name`; lambda refs for `RelatedOrder`; retire the `_building` guard. |
| `aggregate_arguments_factory.py` | `__init__` | Drop `input_type_prefix` param; derive root + per-field names from `aggregate_class.__name__`. |
| `aggregate_arguments_factory.py` | `build_aggregate_type` | Class-based root + sub-type names; child factory constructed without a prefix; optional lambda refs for `RelatedAggregate`. |
| `connection_field.py` | `__init__` | Deprecate `filter_input_type_prefix` and `order_input_type_prefix` kwargs — `DeprecationWarning` + no-op, remove in 1.1. |
| `connection_field.py` | `aggregate_type` property | Drop node-name prefix construction; construct factory with only `aggregate_class`. |
| `connection_field.py` | `order_input_type_prefix` property | Remove entirely. |
| `connection_field.py` | `filter_input_type_prefix` property | Remove entirely. |
| `object_type.py` | `_inject_aggregates_on_connection` | Drop node-name prefix so nested and root aggregate types hit the same cache entry. |
| `filterset.py` | `AdvancedFilterSet` | Add `type_name_for(field_name=None)` classmethod. |
| `orderset.py` | `AdvancedOrderSet` | Add `type_name_for()` classmethod. |
| `aggregateset.py` | `AdvancedAggregateSet` | Add `type_name_for(field_name=None)` classmethod. |
| `filterset_factories.py` | `get_filterset_class` | Memoize the dynamic `custom_filterset_factory` branch by `(model, frozenset(fields.items()))`. |

12 tags across 9 files. Implementing each tagged TODO (top-to-bottom or dependency-order starting with the base-class helpers) lands the whole rename.

---

## Frontend consequences (what this enables)

With stable names in the schema, the frontend can:

1. **Drop `filter_input_type_prefix` / `order_input_type_prefix` plumbing** — no longer needed.
2. **Add a persistent Pinia schema cache** keyed by type name (`spec-introspection_schema_cache.md`, referenced in the cross-page conversation). One `BrandFilterInputType` entry covers every page that reaches it — direct or through any FK chain.
3. **Skip introspection for already-known types on mount** — a page that only touches types present in the persistent cache runs zero `__type` queries. Refresh persists across sessions via `localStorage`.
4. **Remove the `findLocalPath` suffix-matching in `reconcileFilters.ts`** *(optional)* — with identical type names, a stored `CanonicalFilter` path can be matched by exact type at the leaf rather than by field-name suffix. Less fragile. Consider in a follow-up.

---

## Testing

- **Schema snapshot test**: dump the SDL for the cookbook example before and after. Confirm: (a) every type that previously had the node-name-plus-path prefix is now stably named, (b) shared FilterSets/OrderSets/AggregateSets appear exactly once in the SDL.
- **Integration test**: `tools(filter: { brand: { name: { exact: "x" } } })` and `toolMetrics(filter: { tool: { brand: { name: { exact: "x" } } } })` must reference the same `BrandFilterNameFilterInputType` in introspection.
- **Cycle test**: `ObjectFilter ↔ ValueFilter` circular reference still resolves — the lambda-based reference is the standard graphene mechanism for self-referential types.
- **Collision test**: two `BrandFilter` classes in different modules raise at schema-build time unless one declares `Meta.type_name_override`.
- **Existing test suite**: update every assertion on generated type names. The assertions on *shape* stay identical.

---

## Open questions

1. **Suffix for filter per-field types**. Three candidates:
   - `{Class}{Field}FilterInputType` — e.g. `BrandFilterNameFilterInputType`. Keeps the historical `FilterInputType` suffix on the operator bag. "Filter" appears twice in the final string (once from the class name, once from the suffix) but the doubling parallels today's naming and preserves the visual cue that this is an operator-level input type.
   - `{Class}{Field}InputType` — e.g. `BrandFilterNameInputType`. Terser and uniform with the root (`BrandFilterInputType`), but drops the "this is a filter" signal from the leaf type.
   - `{Class}{Field}LookupInputType` — e.g. `BrandFilterNameLookupInputType`. Most semantically precise but introduces a new concept ("Lookup") into the naming vocabulary.
   *Default: option A (`FilterInputType`). It's the smallest delta from today's pattern, matches graphene-django idioms, and avoids inventing new noun suffixes.*
2. **Second-order win: extract leaf lookup types across classes** — if both `BrandFilter.name` and `ObjectFilter.name` declare identical lookup sets on a CharField, they could share a `CharFieldFilterInputType` (the django-filter built-in style). Real savings only if many classes use identical configs. **Defer to a follow-up spec** — not blocking for 1.0.
3. **`Meta.type_name_override`** — should this exist at all? If class names are always unique in practice (they already have to be unique within a module), we can drop it and reduce API surface. *Lean: drop it. Reintroduce only if a concrete need appears.*
4. **Do we rename the generated `Trimmed{FilterSet}` class** in `connection_field._get_trimmed_filterset_class`? It's internal only and never reaches the schema. **No.**
