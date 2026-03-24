"""Permission utilities for django-graphene-filters.

Provides base permission classes and a utility function for cascading
FK-based permission filtering in GraphQL node types.
"""

import threading
from typing import Any

from django.db import models
from graphene_django import DjangoObjectType


class BasePermission:
    """Queryset-level permission for filtering visible rows.

    Subclass and override ``filter_queryset`` to implement custom
    visibility logic.
    """

    def filter_queryset(self, queryset: models.QuerySet, info: Any) -> models.QuerySet:
        """Return a filtered queryset containing only visible rows.

        Args:
            queryset: The base queryset to filter.
            info: The GraphQL ResolveInfo object.

        Returns:
            A filtered queryset.
        """
        return queryset


class AllowAny(BasePermission):
    """No-op permission. All rows are visible."""


class IsAuthenticated(BasePermission):
    """Only authenticated users see rows; anonymous users see nothing."""

    def filter_queryset(self, queryset: models.QuerySet, info: Any) -> models.QuerySet:
        """Return the queryset if the user is authenticated, otherwise empty.

        Args:
            queryset: The base queryset to filter.
            info: The GraphQL ResolveInfo object.

        Returns:
            The original queryset or an empty queryset.
        """
        user = getattr(info.context, "user", None)
        if user and user.is_authenticated:
            return queryset
        return queryset.none()


# Thread-local storage for cycle detection in apply_cascade_permissions
_cascade_context = threading.local()


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

    # Cycle detection via thread-local seen set
    if not hasattr(_cascade_context, "seen"):
        _cascade_context.seen = set()

    seen = _cascade_context.seen
    is_root_call = len(seen) == 0

    if node_class in seen:
        return queryset  # break cycle
    seen.add(node_class)

    try:
        registry = get_global_registry()
        model = node_class._meta.model

        for field in model._meta.get_fields():
            # Only concrete FK fields (have a column in the DB)
            if not hasattr(field, "related_model") or not hasattr(field, "column"):
                continue

            # If specific fields requested, skip others
            if fields is not None and field.name not in fields:
                continue

            # Look up the target node type in the graphene registry
            target_type = registry.get_type_for_model(field.related_model)
            if target_type is None or not hasattr(target_type, "get_queryset"):
                continue

            # Build subquery: visible PKs of the target model
            target_qs = target_type.get_queryset(field.related_model.objects, info)

            # Constrain: only rows whose FK points to a visible target
            queryset = queryset.filter(**{f"{field.name}__in": target_qs})

        return queryset
    finally:
        seen.discard(node_class)
        if is_root_call:
            _cascade_context.seen = set()
