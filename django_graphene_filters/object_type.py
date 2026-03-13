"""`AdvancedDjangoObjectType` class module.

Use this instead of `DjangoObjectType` when you need to declare
an `orderset_class` or `search_fields` in the Meta of your node type.
"""

from collections.abc import Sequence

from graphene_django import DjangoObjectType
from graphene_django.types import DjangoObjectTypeOptions


class AdvancedDjangoObjectType(DjangoObjectType):
    """A DjangoObjectType subclass that supports `orderset_class` and `search_fields` in Meta."""

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
