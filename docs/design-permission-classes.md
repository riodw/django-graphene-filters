# DRF-Style Permission Classes for django-graphene-filters

> **Status:** Design / RFC — not yet implemented
> **Date:** 2026-03-20

## Context

**Problem:** When graphene-django nodes define `get_queryset` to hide private rows (e.g., `is_private=False` for non-staff), a parent Object can have a FK to a private ObjectType. GraphQL resolves the Object, but when resolving the nested `objectType` FK, `get_queryset` on the target node filters it out → `None` → `Cannot return null for non-nullable field` error.

**Root cause:** Each node's `get_queryset` operates in isolation. There's no mechanism for a parent queryset to be aware of what its FK targets' permissions will hide.

**Goal:** Design a DRF-inspired permission class system that is declarative, keeps the schema file clean, and solves the nested FK null problem automatically.

---

## Design

### The Permission Class

```python
# django_graphene_filters/permissions.py

class BasePermission:
    """Queryset-level permission (not per-object) for performance."""

    def filter_queryset(self, queryset, info):
        """Return a filtered queryset containing only visible rows."""
        return queryset
```

That's the entire interface. One method. No `get_join_constraints` needed (see auto-introspection below).

Built-in subclasses:

```python
class AllowAny(BasePermission):
    """No-op. Everything visible."""
    pass

class IsAuthenticated(BasePermission):
    def filter_queryset(self, queryset, info):
        user = getattr(info.context, "user", None)
        if user and user.is_authenticated:
            return queryset
        return queryset.none()
```

### Declaration on Node Types

```python
# schema.py — clean, no inline permission logic
from cookbook.recipes.permissions import IsStaffOrPublic

class ObjectTypeNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectTypeFilter
        orderset_class = ObjectTypeOrder
        permission_classes = [IsStaffOrPublic]    # ← NEW

class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Object
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectFilter
        orderset_class = ObjectOrder
        permission_classes = [IsStaffOrPublic]    # ← same class, auto-handles FKs
```

No `get_queryset` overrides. No manual join constraints.

### The Reusable Permission Class

```python
# cookbook/recipes/permissions.py

from django_graphene_filters.permissions import BasePermission

class IsStaffOrPublic(BasePermission):
    """Hide is_private=True rows from non-staff users."""

    def filter_queryset(self, queryset, info):
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return queryset
        return queryset.filter(is_private=False)
```

One class. Reused across all four node types. The same `IsStaffOrPublic` works for ObjectType, Object, Attribute, and Value because they all share the `is_private` field pattern.

---

## How the Nested FK Problem Is Solved: Auto-Introspection

`AdvancedDjangoObjectType.get_queryset` does two things:

1. **Apply this node's permission classes** (direct row visibility)
2. **Walk FK fields → find target node type in registry → apply its permissions as subquery constraints**

```python
# object_type.py (pseudocode)

@classmethod
def get_queryset(cls, queryset, info):
    # Step 1: Apply own permission classes
    for perm_class in cls._meta.permission_classes:
        queryset = perm_class().filter_queryset(queryset, info)

    # Step 2: Auto-introspect FK relationships
    from graphene_django.registry import get_global_registry
    registry = get_global_registry()

    for field in cls._meta.model._meta.get_fields():
        if not hasattr(field, "related_model") or not hasattr(field, "column"):
            continue  # skip non-FK fields

        target_type = registry.get_type_for_model(field.related_model)
        if not target_type or not getattr(target_type._meta, "permission_classes", None):
            continue

        # Build subquery: visible PKs of the target model
        target_qs = field.related_model.objects.all()
        for perm_class in target_type._meta.permission_classes:
            target_qs = perm_class().filter_queryset(target_qs, info)

        # Constrain: only include rows whose FK points to a visible target
        queryset = queryset.filter(**{f"{field.name}__in": target_qs})

    return queryset
```

### Trace Through the Failing Scenario

1. Non-staff user queries `allObjects { edges { node { objectType { name } } } }`
2. `ObjectNode.get_queryset` runs:
   - Step 1: `IsStaffOrPublic` → `.filter(is_private=False)` (hides private Objects)
   - Step 2: Finds FK `object_type → ObjectType`. ObjectTypeNode has `[IsStaffOrPublic]`.
     Builds subquery: `ObjectType.objects.filter(is_private=False)`
     Applies: `.filter(object_type__in=<visible ObjectTypes>)`
3. Result: Objects where BOTH the Object AND its ObjectType are non-private
4. When graphene resolves `objectType` FK → calls `ObjectTypeNode.get_queryset` → filters `is_private=False` → the `.get(pk=pk)` succeeds because Step 2 guaranteed it
5. **No null error.**

---

## Composition: AND Logic

Multiple permission classes are applied in sequence (like DRF):

```python
permission_classes = [IsAuthenticated, IsStaffOrPublic]
# → qs = IsAuthenticated().filter_queryset(qs, info)
# → qs = IsStaffOrPublic().filter_queryset(qs, info)
# Progressively narrower. Both must pass.
```

---

## Circular FK Guard

The auto-introspection uses a `_seen` set to prevent infinite loops:

```python
@classmethod
def get_queryset(cls, queryset, info, _seen=None):
    if _seen is None:
        _seen = set()
    if cls in _seen:
        return queryset  # break cycle
    _seen.add(cls)
    # ... rest of logic, passing _seen to recursive calls
```

---

## Backward Compatibility

- Nodes with manual `get_queryset` overrides and no `permission_classes` → work exactly as before (Python MRO shadows the base class)
- Nodes with BOTH a manual override AND `permission_classes` → the override must call `super().get_queryset(queryset, info)` to opt in
- `permission_classes` defaults to `[]` → no change in behavior for existing code

---

## How This Relates to Existing Permission Patterns

| Layer | What it controls | Mechanism |
|---|---|---|
| **`permission_classes`** (NEW) | Which ROWS are visible | `filter_queryset()` on node's `get_queryset` |
| **`check_<field>_permission`** (existing) | Which FIELDS can be filtered/ordered by | Convention methods on FilterSet/OrderSet |
| **`RelatedFilter(queryset=...)`** (existing) | Hard data scope for a relationship | Static queryset on the filter definition |

These are orthogonal. Permission classes control visibility. Filter permissions control filter-field access. RelatedFilter querysets are static scope boundaries. All three can coexist.

---

## Files to Create/Modify

| File | Change |
|---|---|
| `django_graphene_filters/permissions.py` | **NEW** — `BasePermission`, `AllowAny`, `IsAuthenticated` |
| `django_graphene_filters/object_type.py` | Add `permission_classes` to `__init_subclass_with_meta__`, implement `get_queryset` with auto-introspection |
| `django_graphene_filters/__init__.py` | Export `BasePermission`, `AllowAny`, `IsAuthenticated` |
| `examples/cookbook/cookbook/recipes/permissions.py` | **NEW** — `IsStaffOrPublic` |
| `examples/cookbook/cookbook/recipes/schema.py` | Replace `get_queryset` overrides with `permission_classes = [IsStaffOrPublic]` |

---

## Verification

1. Run existing `test_permissions_nested.py` — the non-staff test should **pass** (no more null error)
2. Run existing `test_permissions.py` — all tests should still pass
3. Run existing test suite — no regressions
4. Manual test: `uv run python manage.py runserver` → GraphiQL → query `allObjects` with nested `objectType` as non-staff user → no errors, no private data leaked

---

## Future Considerations

- **django-guardian integration:** Row-level permissions via `has_perm` checks could be a built-in permission class
- **OR combinator:** `OR(IsStaff, IsOwner)` helper for cases where either permission suffices
- **Caching:** Permission class instances could cache `filter_queryset` results per-request to avoid redundant subqueries when the same target type is FK'd from multiple models
