"""`AdvancedDjangoObjectType` class module.

Use this instead of `DjangoObjectType` when you need to declare
an `orderset_class` or `search_fields` in the Meta of your node type.
"""

import logging
from collections.abc import Sequence
from typing import Any

from graphene_django import DjangoObjectType
from graphene_django.types import DjangoObjectTypeOptions

logger = logging.getLogger("django_graphene_filters.permissions")


class AdvancedDjangoObjectType(DjangoObjectType):
    """A DjangoObjectType subclass that supports `orderset_class` and `search_fields` in Meta.

    Also overrides ``get_node`` so that when ``get_queryset`` hides a row
    (e.g. because it is private), non-nullable FK fields receive a redacted
    sentinel instance instead of ``None`` — which would otherwise cause a
    ``"Cannot return null for non-nullable field"`` GraphQL error.

    .. warning::

        When a FK traverses a hidden (sentinel) node, all objects
        downstream of that sentinel are also redacted — even if the
        current user has access to them individually.  Use
        ``apply_cascade_permissions`` to proactively exclude parent rows
        whose FK targets are hidden if this is unacceptable for your
        use case.
    """

    class Meta:
        """Mark this type as abstract so it is not registered as a concrete node."""

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        orderset_class: type | None = None,
        search_fields: Sequence[str] | None = None,
        _meta: DjangoObjectTypeOptions | None = None,
        **options,
    ) -> None:
        """Capture ``orderset_class`` and ``search_fields`` from Meta and attach them to ``_meta``."""
        if not _meta:
            _meta = DjangoObjectTypeOptions(cls)
        _meta.orderset_class = orderset_class
        _meta.search_fields = search_fields
        super().__init_subclass_with_meta__(_meta=_meta, **options)

    @classmethod
    def _make_sentinel(cls, source_pk: Any = None) -> Any:
        """Create a redacted sentinel instance with ``pk=0``.

        If ``source_pk`` is provided, the sentinel copies the real FK IDs
        from the hidden row so that downstream FK resolution goes through
        ``get_node`` normally.  Visible targets resolve to real objects;
        hidden targets produce their own sentinels.

        This preserves consistency: if a user can see an ObjectType at the
        root level, they also see the real ObjectType when it appears
        through a hidden intermediate (e.g. a private Attribute).
        """
        sentinel = cls._meta.model(pk=0)
        fk_fields = [
            f
            for f in cls._meta.model._meta.get_fields()
            if hasattr(f, "attname") and hasattr(f, "related_model")
        ]
        if source_pk is not None and fk_fields:
            # Copy real FK IDs so visible downstream targets resolve normally.
            attnames = [f.attname for f in fk_fields]
            real_values = cls._meta.model.objects.filter(pk=source_pk).values(*attnames).first()
            if real_values:
                for attname in attnames:
                    setattr(sentinel, attname, real_values[attname])
                return sentinel
        # Fallback: set FK IDs to 0 for safe chain propagation.
        for f in fk_fields:
            setattr(sentinel, f.attname, 0)
        return sentinel

    @classmethod
    def get_node(cls, info: Any, id: Any) -> Any | None:
        """Return the node for *id*, or a redacted sentinel if hidden by ``get_queryset``.

        The default ``DjangoObjectType.get_node`` returns ``None`` when
        ``get_queryset`` filters the row out.  That breaks non-nullable FK
        fields because GraphQL cannot coerce ``None`` into a concrete type.

        This override detects the "row exists but is hidden" case and returns
        a sentinel instance with ``pk=0`` and all other fields at their
        defaults — so the FK resolves without leaking private data.

        The sentinel preserves the hidden row's real FK IDs so that
        visible downstream objects resolve normally.  If a downstream
        target is also hidden, it produces its own sentinel — the chain
        is handled recursively by each type's ``get_node``.

        The Relay global ID encodes to ``<TypeName>:0`` (e.g.
        ``T2JqZWN0VHlwZU5vZGU6MA==``), signalling to clients that the
        relationship exists but the target is not accessible.
        """
        # Sentinel chain: propagate when a parent sentinel's FK ID
        # could not be resolved (fallback value of 0).
        if id == 0:
            return cls._make_sentinel()

        if id is None:
            return None

        queryset = cls.get_queryset(cls._meta.model.objects, info)
        try:
            return queryset.get(pk=id)
        except cls._meta.model.DoesNotExist:
            if cls._meta.model.objects.filter(pk=id).exists():
                # The row exists but get_queryset hid it.  Return a
                # redacted sentinel so non-nullable FK fields don't break.
                logger.info(
                    "Sentinel returned for %s pk=%s — row hidden by get_queryset. "
                    "Downstream objects reachable only through this FK will also "
                    "appear as sentinels even if the user has direct access to them. "
                    "Use apply_cascade_permissions() in get_queryset to exclude "
                    "parent rows whose FK targets are hidden.",
                    cls.__name__,
                    id,
                )
                return cls._make_sentinel(source_pk=id)
            return None
