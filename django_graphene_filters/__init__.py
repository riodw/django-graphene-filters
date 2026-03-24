"""django-graphene-filters source.

This package provides advanced filtering capabilities for Django with Graphene.
"""

from .connection_field import AdvancedDjangoFilterConnectionField
from .filters import (
    # Explicitly import the classes and methods
    AnnotatedFilter,
    BaseRelatedFilter,
    RelatedFilter,
    SearchQueryFilter,
    SearchRankFilter,
    TrigramFilter,
)
from .filterset import AdvancedFilterSet
from .object_type import AdvancedDjangoObjectType
from .orders import BaseRelatedOrder, RelatedOrder
from .orderset import AdvancedOrderSet
from .permissions import AllowAny, BasePermission, IsAuthenticated, apply_cascade_permissions

__version__ = "0.3.1"

# All classes, methods, part of the public API
# easier to manage and understand the package
__all__ = [
    "AnnotatedFilter",
    "SearchQueryFilter",
    "SearchRankFilter",
    "TrigramFilter",
    "BaseRelatedFilter",
    "RelatedFilter",
    "AdvancedDjangoFilterConnectionField",
    "AdvancedDjangoObjectType",
    "AdvancedFilterSet",
    "BaseRelatedOrder",
    "RelatedOrder",
    "AdvancedOrderSet",
    "BasePermission",
    "AllowAny",
    "IsAuthenticated",
    "apply_cascade_permissions",
]
