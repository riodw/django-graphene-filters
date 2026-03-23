"""`AdvancedDjangoObjectType` class module.

Use this instead of `DjangoObjectType` when you need to declare
an `orderset_class` or `search_fields` in the Meta of your node type.
"""

from collections.abc import Sequence
from typing import Any

from graphene_django import DjangoObjectType
from graphene_django.types import DjangoObjectTypeOptions


class AdvancedDjangoObjectType(DjangoObjectType):
    """A DjangoObjectType subclass that supports `orderset_class` and `search_fields` in Meta.

    Also overrides ``get_node`` so that when ``get_queryset`` hides a row
    (e.g. because it is private), non-nullable FK fields receive a redacted
    sentinel instance instead of ``None`` — which would otherwise cause a
    ``"Cannot return null for non-nullable field"`` GraphQL error.
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
    def get_node(cls, info: Any, id: Any) -> Any | None:
        """Return the node for *id*, or a redacted sentinel if hidden by ``get_queryset``.

        The default ``DjangoObjectType.get_node`` returns ``None`` when
        ``get_queryset`` filters the row out.  That breaks non-nullable FK
        fields because GraphQL cannot coerce ``None`` into a concrete type.

        This override detects the "row exists but is hidden" case and returns
        a sentinel instance with ``pk=0`` and all other fields at their
        defaults — so the FK resolves without leaking private data.

        The Relay global ID encodes to ``<TypeName>:0`` (e.g.
        ``T2JqZWN0VHlwZU5vZGU6MA==``), signalling to clients that the
        relationship exists but the target is not accessible.
        """
        queryset = cls.get_queryset(cls._meta.model.objects, info)
        try:
            return queryset.get(pk=id)
        except cls._meta.model.DoesNotExist:
            # The row exists in the DB but get_queryset hid it (e.g. private).
            # Return a redacted sentinel (pk=0) so non-nullable FK fields
            # don't break. pk=0 never matches a real row.
            if cls._meta.model.objects.filter(pk=id).exists():
                return cls._meta.model(pk=0)
            return None
