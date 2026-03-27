# Field-Level Permissions — `AdvancedFieldSet` / `fields_class`

**Status:** Proposed

## Overview

The library provides an `AdvancedFieldSet` base class — following the same pattern as `AdvancedFilterSet` / `AdvancedOrderSet` / `AdvancedAggregateSet`. Consumers define their own field-permission classes declaring `check_<field>_permission(info)` methods that control which fields are visible to which users at resolve time.

This is **resolve-time enforcement** (option 1): fields still appear in the GraphQL schema introspection for all users, but unauthorized fields resolve to `null` instead of their actual value. This avoids the complexity of per-role schema generation while providing practical column-level security.

The design completes the four-layer permission model:

| Layer | Class | Controls | Meta param |
|---|---|---|---|
| Row-level | `AdvancedDjangoObjectType` | Which **rows** are visible | `get_queryset()` |
| Filter | `AdvancedFilterSet` | Which fields can be **filtered on** | `filterset_class` |
| Order | `AdvancedOrderSet` | Which fields can be **ordered by** | `orderset_class` |
| Aggregate | `AdvancedAggregateSet` | Which fields can be **aggregated** | `aggregate_class` |
| **Field** | **`AdvancedFieldSet`** | **Which fields can be seen in results** | **`fields_class`** |

All five layers are **independent** — a user can be allowed to filter by a field they can't see in results, or see a field they can't order by.

---

## Example Project Usage (Cookbook)

### 1. Define Field Permission Classes

```python
# examples/cookbook/cookbook/recipes/fieldsets.py

import django_graphene_filters as fieldsets
from graphql import GraphQLError
from . import models


class ObjectTypeFieldSet(fieldsets.AdvancedFieldSet):
    class Meta:
        model = models.ObjectType

    def check_description_permission(self, info):
        """Only staff can see ObjectType descriptions."""
        user = getattr(info.context, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("Not authorized to view description.")


class ObjectFieldSet(fieldsets.AdvancedFieldSet):
    class Meta:
        model = models.Object

    def check_is_private_permission(self, info):
        """Hide the is_private flag from non-staff."""
        user = getattr(info.context, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("Not authorized.")


class ValueFieldSet(fieldsets.AdvancedFieldSet):
    class Meta:
        model = models.Value

    def check_value_permission(self, info):
        """Only authenticated users can see actual values."""
        user = getattr(info.context, "user", None)
        if not user or not user.is_authenticated:
            raise GraphQLError("Login required to view values.")

    def check_description_permission(self, info):
        """Only staff can see value descriptions."""
        user = getattr(info.context, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("Staff only.")
```

### 2. Wire Up in Schema

```python
# examples/cookbook/cookbook/recipes/schema.py

from .fieldsets import ObjectFieldSet, ObjectTypeFieldSet, ValueFieldSet

class ObjectTypeNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectTypeFilter
        orderset_class = ObjectTypeOrder
        aggregate_class = ObjectTypeAggregate
        fields_class = ObjectTypeFieldSet  # NEW

class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Object
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectFilter
        orderset_class = ObjectOrder
        aggregate_class = ObjectAggregate
        fields_class = ObjectFieldSet  # NEW

class ValueNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Value
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ValueFilter
        orderset_class = ValueOrder
        aggregate_class = ValueAggregate
        fields_class = ValueFieldSet  # NEW
```

### 3. GraphQL Queries

**Staff user sees everything:**
```graphql
query {
  allObjectTypes {
    edges {
      node {
        name
        description  # ✅ Visible — user is staff
      }
    }
  }
}
# → { "name": "People", "description": "Human beings" }
```

**Non-staff user — restricted field returns null:**
```graphql
query {
  allObjectTypes {
    edges {
      node {
        name
        description  # ❌ Returns null — user is not staff
      }
    }
  }
}
# → { "name": "People", "description": null }
```

**Anonymous user — multiple restricted fields:**
```graphql
query {
  allValues {
    edges {
      node {
        value        # ❌ Returns null — not authenticated
        description  # ❌ Returns null — not staff
        attribute { name }  # ✅ Visible — no restriction
      }
    }
  }
}
```

### 4. Permission Behaviour

The permission convention:

- `check_<field>_permission(info)` **does not raise** → field resolves normally (permission granted)
- `check_<field>_permission(info)` **raises an exception** → field is denied:
  - **Nullable fields** → resolve to `None`
  - **Non-nullable fields** → GraphQL error for that specific field (partial error)

This matches the existing convention on `AdvancedFilterSet`, `AdvancedOrderSet`, and `AdvancedAggregateSet` where raising blocks the operation.

### 5. Resolve Methods — Custom & Override Content

Beyond permission checks, the FieldSet supports `resolve_<field>(root, info)` methods that **replace** the default resolver entirely. This enables three patterns:

#### a) Custom computed fields

Return a value that doesn't exist on the model — useful for derived/virtual fields:

```python
class PersonFieldSet(AdvancedFieldSet):
    class Meta:
        model = Person

    def resolve_display_name(self, root, info):
        """Computed field: full name from first + last."""
        return f"{root.first_name} {root.last_name}"

    def resolve_age(self, root, info):
        """Computed field: age from date_of_birth."""
        from datetime import date
        if root.date_of_birth:
            today = date.today()
            return today.year - root.date_of_birth.year
        return None
```

Note: the GraphQL field must still be declared on the ObjectType (e.g. via a `graphene.String()` class attribute). The FieldSet only controls the resolver, not the schema.

#### b) Role-based content overrides (masking)

Return different content for the same field depending on the user's role:

```python
class PersonFieldSet(AdvancedFieldSet):
    class Meta:
        model = Person

    def resolve_email(self, root, info):
        """Staff sees real email; others see masked version."""
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return root.email  # Real value
        if root.email:
            local, domain = root.email.split("@")
            return f"{local[0]}***@{domain}"  # Masked: j***@example.com
        return None

    def resolve_phone(self, root, info):
        """Authenticated users see last 4 digits; anonymous gets null."""
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return root.phone
        if user and user.is_authenticated:
            return f"***-***-{root.phone[-4:]}"  # Partial: ***-***-1234
        return None  # Anonymous gets nothing

    def resolve_ssn(self, root, info):
        """Only superusers see SSN; everyone else gets redacted."""
        user = getattr(info.context, "user", None)
        if user and user.is_superuser:
            return root.ssn
        return "***-**-****"
```

**Query result for a regular authenticated user:**
```json
{
  "name": "Alice Johnson",
  "email": "a***@example.com",
  "phone": "***-***-5678",
  "ssn": "***-**-****"
}
```

#### c) Model field override with DB-computed content

Replace a model field's value with something computed from the DB based on context:

```python
class ObjectFieldSet(AdvancedFieldSet):
    class Meta:
        model = Object

    def resolve_description(self, root, info):
        """Non-staff see a truncated description."""
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return root.description
        if root.description and len(root.description) > 50:
            return root.description[:50] + "..."
        return root.description

    def resolve_name(self, root, info):
        """Append '[PRIVATE]' tag for staff viewing private objects."""
        if root.is_private:
            user = getattr(info.context, "user", None)
            if user and user.is_staff:
                return f"{root.name} [PRIVATE]"
        return root.name
```

### 6. Resolution Order (Cascade)

For each managed field, the resolver runs a three-step cascade:

1. **`check_<field>_permission`** → if defined, runs first as a gate. Raises → field denied (`null`), cascade stops. Doesn't raise → continue.
2. **`resolve_<field>`** → if defined, runs next as a content override. Receives `(self, root, info)` and returns the field value. Can assume the permission check already passed.
3. **Default resolver** → `getattr(root, field_name)` or graphene-django's FK resolver. Only reached if no `resolve_<field>` is defined.

All three compose naturally. Define whichever you need:

| Defined | Behaviour |
|---|---|
| Only `check_` | Gate → default resolver |
| Only `resolve_` | No gate → custom resolver |
| Both | Gate → custom resolver (resolve can assume user passed the check) |
| Neither | Default resolver (field not managed, no overhead) |

Example with both:

```python
class PersonFieldSet(AdvancedFieldSet):
    class Meta:
        model = Person

    def check_email_permission(self, info):
        """Gate: anonymous users get null."""
        user = getattr(info.context, "user", None)
        if not user or not user.is_authenticated:
            raise GraphQLError("Login required")

    def resolve_email(self, root, info):
        """Content: staff sees real email, others see masked.
        Can safely assume user is authenticated (check passed).
        """
        if info.context.user.is_staff:
            return root.email
        local, domain = root.email.split("@")
        return f"{local[0]}***@{domain}"
```

### 5. Independent Permission Layers

Each layer is evaluated independently. The same field can have different rules across layers:

```python
# filters.py — Only admins can FILTER BY email
class PersonFilter(AdvancedFilterSet):
    def check_email_permission(self, request):
        if not request.user.is_superuser:
            raise GraphQLError("Cannot filter by email")

# orders.py — Anyone authenticated can ORDER BY email
class PersonOrder(AdvancedOrderSet):
    def check_email_permission(self, request):
        if not request.user.is_authenticated:
            raise GraphQLError("Login to sort by email")

# aggregates.py — Only admins can AGGREGATE email
class PersonAggregate(AdvancedAggregateSet):
    def check_email_permission(self, request):
        if not request.user.is_superuser:
            raise GraphQLError("Cannot aggregate email")

# fieldsets.py — Staff can SEE email values
class PersonFieldSet(AdvancedFieldSet):
    def check_email_permission(self, info):
        if not info.context.user.is_staff:
            raise GraphQLError("Cannot view email")
```

Result: a staff (non-admin) user can see emails and sort by them, but cannot filter or aggregate them. An authenticated non-staff user can sort by email but not see, filter, or aggregate it.

---

## Package Changes (`django_graphene_filters`)

### New Files

#### `fieldset.py` — The `AdvancedFieldSet` base class

This is the core module. It contains:

**`FieldSetMetaclass`** — validates configuration at class creation time:

```python
class FieldSetMetaclass(type):
    def __new__(cls, name, bases, attrs):
        new_class = super().__new__(cls, name, bases, attrs)
        meta = getattr(new_class, "Meta", None)
        if meta and getattr(meta, "model", None):
            model = meta.model
            # 1. Discover check_<field>_permission AND resolve_<field> methods
            # 2. Validate each field exists on the model
            #    (resolve_<field> may target computed fields not on the model
            #     — skip validation for those; they must be declared on the
            #     ObjectType as graphene fields)
            # 3. Store validated config as:
            #    new_class._field_permissions = {"email", "description", ...}
            #    new_class._field_resolvers = {"display_name", "age", ...}
            #    new_class._managed_fields = union of both sets
        return new_class
```

**`AdvancedFieldSet`** — the base class consumers inherit from:

```python
class AdvancedFieldSet(metaclass=FieldSetMetaclass):

    class Meta:
        model = None

    def __init__(self, info):
        self.info = info
        self.request = info.context

    def check_field(self, field_name):
        """Check if the current user can see the given field.

        Returns True if allowed, False if denied.
        """
        method = getattr(self, f"check_{field_name}_permission", None)
        if method is None:
            return True  # No restriction
        try:
            method(self.info)
            return True
        except Exception:
            return False

    def has_resolve_method(self, field_name):
        """Check if a resolve_<field> override exists."""
        return hasattr(self, f"resolve_{field_name}")

    def resolve_field(self, field_name, root, info):
        """Call the resolve_<field> override for custom content."""
        method = getattr(self, f"resolve_{field_name}")
        return method(root, info)
```

The resolver wrapper uses two methods:

**`check_field(field_name)`** — permission gate:
1. Looks up `check_<field>_permission` on the instance
2. If no method exists → field is unrestricted (returns `True`)
3. If method exists and doesn't raise → field is allowed (returns `True`)
4. If method raises → field is denied (returns `False`)

**`resolve_field(field_name, root, info)`** — custom resolver:
1. Called after `check_field` passes (or if no check exists)
2. Replaces the default resolver for content transformation
3. Can assume the user already passed the permission gate

### Modified Files

#### `object_type.py` — Accept `fields_class` in Meta and wrap resolvers

This is the main integration point. Two changes:

**a) Accept `fields_class` parameter:**

```python
@classmethod
def __init_subclass_with_meta__(
    cls,
    orderset_class=None,
    search_fields=None,
    aggregate_class=None,
    fields_class=None,  # NEW
    _meta=None,
    **options,
):
    if not _meta:
        _meta = DjangoObjectTypeOptions(cls)
    _meta.orderset_class = orderset_class
    _meta.search_fields = search_fields
    _meta.aggregate_class = aggregate_class
    _meta.fields_class = fields_class  # NEW
    super().__init_subclass_with_meta__(_meta=_meta, **options)

    # ... existing aggregate/sentinel logic ...

    # NEW: wrap resolvers for fields with permission checks
    if fields_class:
        _wrap_field_resolvers(cls, fields_class)
```

**b) Resolver wrapping function:**

```python
def _wrap_field_resolvers(node_cls, fields_class):
    """Wrap resolvers for fields that have permission checks on the FieldSet.

    For each check_<field>_permission method on the fields_class,
    find the corresponding field on the node type and wrap its resolver.
    The wrapper checks permission before resolving; if denied, returns None.
    """
    for field_name in fields_class._managed_fields:
        # Convert model field name to GraphQL field name
        # (graphene converts snake_case → camelCase)
        graphql_name = to_camel_case(field_name)

        if graphql_name not in node_cls._meta.fields:
            continue

        graphene_field = node_cls._meta.fields[graphql_name]
        original_resolver = graphene_field.resolver

        def make_wrapper(fname, orig):
            def permission_checking_resolver(root, info, **kwargs):
                fieldset = fields_class(info)

                # Step 1: Permission gate (always runs first if defined)
                if not fieldset.check_field(fname):
                    return None  # Permission denied → null

                # Step 2: Custom resolver (runs if defined, check already passed)
                if fieldset.has_resolve_method(fname):
                    return fieldset.resolve_field(fname, root, info)

                # Step 3: Default resolver (no custom resolve defined)
                if orig:
                    return orig(root, info, **kwargs)
                return getattr(root, fname, None)
            return permission_checking_resolver

        graphene_field.resolver = make_wrapper(field_name, original_resolver)
```

This approach:
- Runs automatically when `fields_class` is set in Meta — **no middleware needed**
- Only wraps fields that have permission checks — **zero overhead** on unrestricted fields
- Instantiates the `AdvancedFieldSet` per-resolution — gives access to `info` (request context)
- Returns `None` for denied fields (consumers can subclass to raise instead)

#### `__init__.py` — Export new public API

```python
from .fieldset import AdvancedFieldSet

__all__ = [
    # ... existing exports ...
    "AdvancedFieldSet",
]
```

---

## How It Flows

```
1. Schema startup
   ├─ FieldSetMetaclass validates Meta.model
   │  ├─ Discovers check_<field>_permission and resolve_<field> methods
   │  ├─ Validates model fields exist (resolve_ methods may target computed fields)
   │  └─ Stores _field_permissions, _field_resolvers, _managed_fields
   ├─ Consumer defines ObjectFieldSet(AdvancedFieldSet)
   ├─ ObjectNode Meta has fields_class = ObjectFieldSet
   ├─ __init_subclass_with_meta__ calls _wrap_field_resolvers()
   │  ├─ For each field in _field_permissions:
   │  │  ├─ Find corresponding graphene field on the node type
   │  │  └─ Replace its resolver with a permission-checking wrapper
   │  └─ Unrestricted fields are untouched
   └─ Schema is built normally (all fields visible in introspection)

2. Query execution
   ├─ GraphQL resolves each field on the node
   ├─ For unrestricted fields → standard resolver (no overhead)
   └─ For managed fields → wrapper resolver runs:
      ├─ Instantiate AdvancedFieldSet(info)
      ├─ Step 1: check_<field>_permission exists?
      │  ├─ Raises → return None (denied, cascade stops)
      │  └─ Doesn't raise → continue
      ├─ Step 2: resolve_<field> exists?
      │  └─ YES → call it (can assume check passed) → return value
      ├─ Step 3: default resolver → getattr(root, field_name)
      └─ Result returned to GraphQL engine

3. Response examples
   └─ Permission denied:  { "name": "Alice", "email": null }
   └─ Masked:            { "name": "Alice", "email": "a***@example.com" }
   └─ Computed:          { "displayName": "Alice Johnson", "age": 32 }
```

---

## Permission Hooks

Following the existing `check_*_permission` pattern:

```python
class PersonFieldSet(AdvancedFieldSet):
    class Meta:
        model = Person

    def check_email_permission(self, info):
        """Block email for non-staff."""
        user = getattr(info.context, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("Not authorized to view email.")

    def check_ssn_permission(self, info):
        """Block SSN for everyone except superusers."""
        user = getattr(info.context, "user", None)
        if not user or not user.is_superuser:
            raise GraphQLError("Not authorized to view SSN.")

    def check_phone_permission(self, info):
        """Block phone for anonymous users."""
        user = getattr(info.context, "user", None)
        if not user or not user.is_authenticated:
            raise GraphQLError("Login required.")
```

The permission check convention:
- `check_<field>_permission(info)` — runs before resolving the field
- **Raises** → field denied (nullable → `None`, non-nullable → field-level GraphQL error)
- **Does not raise** → field resolves normally

Note: `info` is the full graphene `ResolveInfo` object, which provides `info.context` (the Django `HttpRequest`), `info.field_name`, `info.parent_type`, etc.

---

## Backwards Compatibility & Validation

### `fields` without `fields_class` — unchanged behaviour

Existing nodes that don't use `fields_class` work exactly as they do today. No resolver wrapping occurs, no overhead:

```python
# ✅ Works — all model fields in schema, no permission wrapping
class ObjectTypeNode(AdvancedDjangoObjectType):
    class Meta:
        model = ObjectType
        interfaces = (Node,)
        fields = "__all__"

# ✅ Works — only name and description in schema, no permission wrapping
class ObjectTypeNode(AdvancedDjangoObjectType):
    class Meta:
        model = ObjectType
        interfaces = (Node,)
        fields = ["name", "description"]
```

### `fields_class` with `fields` — coexistence and validation

`fields` (graphene-django) and `fields_class` serve different purposes and coexist:
- `fields` controls **schema presence** — which fields exist in the GraphQL type
- `fields_class` controls **resolve-time visibility** — which fields return real values vs `null`

Both must still be defined on the Node. `fields_class` does not replace `fields`.

When `fields = "__all__"`, no validation is needed — all model fields are in the schema so any FieldSet method can target them.

When `fields = ["name", "description"]`, the library validates that every field referenced by the FieldSet (via `check_<field>_permission` or `resolve_<field>`) is present in the `fields` list. If a FieldSet references a field that is **not** in the schema, a warning is logged at startup:

```python
# ⚠️ WARNING at startup — FieldSet references a field not in the schema
class ObjectTypeNode(AdvancedDjangoObjectType):
    class Meta:
        model = ObjectType
        interfaces = (Node,)
        fields = ["name"]  # description not included
        fields_class = ObjectTypeFieldSet  # has check_description_permission

# Logs:
# WARNING: ObjectTypeFieldSet references field 'description' but it is not in
# ObjectTypeNode's fields list. The permission/resolve method will have no effect.
```

The validation in `_wrap_field_resolvers`:

```python
def _wrap_field_resolvers(node_cls, fields_class):
    for field_name in fields_class._managed_fields:
        graphql_name = to_camel_case(field_name)

        if graphql_name not in node_cls._meta.fields:
            logger.warning(
                "%s references field '%s' but it is not in %s's fields list. "
                "The permission/resolve method will have no effect.",
                fields_class.__name__,
                field_name,
                node_cls.__name__,
            )
            continue

        # ... wrap the resolver ...
```

This is a warning, not an error, because it's not necessarily a bug — a consumer might intentionally share a FieldSet across multiple nodes where different fields are exposed.

### Valid combinations

| `fields` | `fields_class` | Behaviour |
|---|---|---|
| `"__all__"` | Not set | All fields in schema, no permission wrapping |
| `["name", "desc"]` | Not set | Only listed fields in schema, no permission wrapping |
| `"__all__"` | `MyFieldSet` | All fields in schema, FieldSet manages resolve-time visibility |
| `["name", "desc"]` | `MyFieldSet` | Listed fields in schema, FieldSet wraps those that overlap. Warning for any FieldSet field not in the list. |

---

## Design Decisions

### Why `info` instead of `request`?

FilterSet/OrderSet/AggregateSet receive `request` because they are instantiated once per query at the connection-field level. FieldSet permission checks run per-field-per-row, and receive `info` because:
1. `info.context` gives access to the request
2. `info` also provides the field name and parent type — useful for context-aware checks
3. The resolver signature already has `info` available — no extra plumbing needed

### Why resolver wrapping instead of middleware?

- **Zero config** — works automatically when `fields_class` is set on Meta
- **Selective** — only wraps fields with permission checks (no overhead on unrestricted fields)
- **Consistent** — follows the library's Meta-driven pattern, not a separate schema-level concern

### Why not hide fields from introspection?

That would require per-role schema generation (the Hasura approach). Graphene builds one schema at startup for all users. Per-role schemas would require:
- Multiple schema instances in memory
- A custom `GraphQLView` that routes to the right schema per request
- Static role declarations (can't use dynamic Django permissions)

Resolve-time enforcement is the pragmatic choice. Fields appear in introspection but return `null` when unauthorized — the same approach Hasura uses for inherited roles with partial column overlap.

### Nullable vs. non-nullable fields

When a permission check denies a field:
- **Nullable fields** → resolve to `None` (safe, no error)
- **Non-nullable fields** → the wrapper returns `None`, which causes a GraphQL field-level error (`"Cannot return null for non-nullable field"`)

This is intentional: if a field is non-nullable in the schema and a user can't see it, that's a configuration issue the developer should be aware of. Options for the developer:
1. Make the field nullable in the GraphQL schema (via a custom graphene `Field` declaration)
2. Don't restrict non-nullable fields (restrict at the row level via `get_queryset` instead)
3. Accept the field-level error as the desired behaviour

---

## Package Changes Summary

### New Files

**Library:**
- `django_graphene_filters/fieldset.py` — `AdvancedFieldSet` base class + `FieldSetMetaclass`

**Example:**
- `examples/cookbook/cookbook/recipes/fieldsets.py` — field permission classes for all 4 models

### Modified Files

**Library:**
- `django_graphene_filters/object_type.py` — add `fields_class` param + `_wrap_field_resolvers()`
- `django_graphene_filters/__init__.py` — export `AdvancedFieldSet`

**Example:**
- `examples/cookbook/cookbook/recipes/schema.py` — add `fields_class` to each node's Meta

### Test Files

- `tests/test_fieldset.py` — unit tests for `AdvancedFieldSet` (metaclass validation, check_field, resolver wrapping)
- `examples/cookbook/cookbook/recipes/tests/test_field_permissions.py` — integration tests via live GraphQL queries

---

## Estimated Effort

- **New files:** 1 library module (`fieldset.py`), 1 example module (`fieldsets.py`)
- **Modified files:** 2 (`object_type.py`, `__init__.py`)
- **Test files:** 2
- **Complexity:** Low-Medium — simpler than aggregates (no computation, no factory, no type generation). The main work is the resolver wrapping logic in `object_type.py` and handling edge cases (camelCase conversion, non-nullable fields, FK fields).
- **Estimated time:** 2-4 days

---

## Risks

- **Non-nullable field errors** — if a developer restricts a non-nullable field, users get a GraphQL error instead of `null`. This is the correct behavior but may surprise developers. Mitigated by clear documentation and a startup warning.
- **Resolver chain interactions** — wrapping resolvers must play nicely with graphene-django's custom FK resolvers (which go through `get_node`) and the sentinel system. Needs careful testing with FK fields.
- **Performance on large result sets** — the permission check runs per-field-per-row. For a query returning 1000 rows with 3 restricted fields, that's 3000 permission checks. Each check is a simple method call (no DB access), so this should be negligible — but it's worth benchmarking.
- **camelCase ↔ snake_case mapping** — graphene converts `field_name` → `fieldName` in the schema. The resolver wrapping must correctly map between the two. `graphene.utils.str_converters.to_camel_case` handles this.

---

## Advantages

- **Consistent pattern** — same `check_<field>_permission` convention as FilterSet/OrderSet/AggregateSet
- **Zero config** — no middleware, no schema-level changes, just `fields_class = ...` in Meta
- **Independent layers** — field visibility is completely decoupled from filter/order/aggregate permissions
- **Lightweight** — no schema generation, no type factories, no new GraphQL types. Just resolver wrapping.
- **Extensible** — `resolve_<field>` methods give full control over field values per role — masking, redaction, computed fields, or entirely custom content
- **Graduated control** — simple fields use `check_<field>_permission` (deny/allow); complex fields use `resolve_<field>` (full override with custom logic)
