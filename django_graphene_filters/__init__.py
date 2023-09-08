"""django-graphene-filters"""
"""
This package provides advanced filtering capabilities for Django with Graphene.
"""

__version__ = "0.0.4"

# Explicitly import the classes and methods
from .filters import (
    AnnotatedFilter,
    SearchQueryFilter,
    SearchRankFilter,
    TrigramFilter,
    BaseRelatedFilter,
    RelatedFilter,
)

from .connection_field import AdvancedDjangoFilterConnectionField
from .filterset import AdvancedFilterSet


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
    "AdvancedFilterSet",
]
