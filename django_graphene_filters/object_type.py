"""`AdvancedDjangoObjectType` class module.

Use this instead of `DjangoObjectType` when you need to declare
an `orderset_class` in the Meta of your node type.
"""

from graphene_django import DjangoObjectType
from graphene_django.types import DjangoObjectTypeOptions


class AdvancedDjangoObjectType(DjangoObjectType):
    """A DjangoObjectType subclass that supports `orderset_class` in Meta."""

    class Meta:
        abstract = True

    @classmethod
    def __init_subclass_with_meta__(cls, orderset_class=None, _meta=None, **options):
        if not _meta:
            _meta = DjangoObjectTypeOptions(cls)
        _meta.orderset_class = orderset_class
        super().__init_subclass_with_meta__(_meta=_meta, **options)
