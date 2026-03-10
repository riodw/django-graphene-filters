"""`AdvancedDjangoObjectType` class module.

Use this instead of `DjangoObjectType` when you need to declare
an `orderset_class` in the Meta of your node type.
"""

from graphene_django import DjangoObjectType
from graphene_django.types import DjangoObjectTypeOptions


class AdvancedDjangoObjectType(DjangoObjectType):
    """A DjangoObjectType subclass that supports `orderset_class` in Meta."""

    class Meta:
        """Mark this type as abstract so it is not registered as a concrete node."""

        abstract = True

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        orderset_class: type | None = None,
        _meta: DjangoObjectTypeOptions | None = None,
        **options,
    ) -> None:
        """Capture ``orderset_class`` from Meta and attach it to ``_meta``."""
        if not _meta:
            _meta = DjangoObjectTypeOptions(cls)
        _meta.orderset_class = orderset_class
        super().__init_subclass_with_meta__(_meta=_meta, **options)
