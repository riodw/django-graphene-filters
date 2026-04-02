"""Permission utilities for django-graphene-filters.

Provides a utility function for cascading FK-based permission filtering
in GraphQL node types.
"""

from contextvars import ContextVar
from typing import Any

from django.db import models
from django.db.models import Q
from graphene_django import DjangoObjectType

# Context-var for cycle detection in apply_cascade_permissions.
# Works correctly for both sync (WSGI) and async (ASGI) Django.
_cascade_seen: ContextVar[set | None] = ContextVar("_cascade_seen", default=None)


def apply_cascade_permissions(
    node_class: type[DjangoObjectType],
    queryset: models.QuerySet,
    info: Any,
    fields: list[str] | None = None,
) -> models.QuerySet:
    """Filter out rows whose FK targets are hidden by the target node's ``get_queryset``.

    Use this inside a node's ``get_queryset`` to enforce cascading visibility:
    rows are excluded if their FK points to a target that the current user
    cannot see.

    Args:
        node_class: The ``AdvancedDjangoObjectType`` subclass (pass ``cls``
            from within ``get_queryset``).
        queryset: The queryset to constrain.
        info: The GraphQL ``ResolveInfo`` object.
        fields: Optional list of FK field names to cascade through. If
            ``None``, all concrete FK fields are cascaded.

    Returns:
        A queryset filtered to exclude rows whose FK targets are hidden.

    Example::

        @classmethod
        def get_queryset(cls, queryset, info):
            user = getattr(info.context, "user", None)
            if user and user.is_staff:
                return queryset
            qs = queryset.filter(is_private=False)
            return apply_cascade_permissions(cls, qs, info, fields=["object_type"])
    """
    from graphene_django.registry import get_global_registry

    # Cycle detection via context-var seen set
    seen = _cascade_seen.get()
    is_root_call = seen is None
    if is_root_call:
        seen = set()
        _cascade_seen.set(seen)

    if node_class in seen:
        return queryset  # break cycle
    seen.add(node_class)

    try:
        registry = get_global_registry()
        model = node_class._meta.model

        for field in model._meta.get_fields():
            # Only single-column FK / OneToOneField relations.
            # ManyToManyField does NOT have a "column" attribute (it's
            # backed by a join table), so this check is precise.
            if getattr(field, "related_model", None) is None or not hasattr(field, "column"):
                continue

            # If specific fields requested, skip others
            if fields is not None and field.name not in fields:
                continue

            # Look up the target node type in the graphene registry
            target_type = registry.get_type_for_model(field.related_model)
            if target_type is None or not hasattr(target_type, "get_queryset"):
                continue

            # Build subquery: visible PKs of the target model.
            # Use _default_manager instead of .objects to support models
            # that override the default manager name.
            target_qs = target_type.get_queryset(field.related_model._default_manager.all(), info)

            # Constrain: only rows whose FK points to a visible target.
            # Nullable FK rows (NULL) are preserved — they don't reference
            # a hidden target, so they should remain visible.
            queryset = queryset.filter(
                Q(**{f"{field.name}__in": target_qs}) | Q(**{f"{field.name}__isnull": True})
            )

        return queryset
    finally:
        seen.discard(node_class)
        if is_root_call:
            _cascade_seen.set(None)
