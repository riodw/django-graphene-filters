"""
Functions for creating a FilterSet class.
"""

from typing import Optional, Type, Any, Dict

from graphene_django.filter.filterset import custom_filterset_factory, setup_filterset
from graphene_django.filter.utils import replace_csv_filters

from .filterset import AdvancedFilterSet


def get_filterset_class(
    filterset_class: Optional[Type[AdvancedFilterSet]],
    **meta: Dict[str, Any],
) -> Type[AdvancedFilterSet]:
    """
    Returns a FilterSet class to be used for filtering in GraphQL queries.

    This function is a partial copy of the `get_filterset_class` function from graphene-django.
    See: https://github.com/graphql-python/graphene-django/blob/caf954861025b9f3d9d3f9c204a7cbbc87352265/graphene_django/filter/utils.py#L56

    Args:
        filterset_class: An optional base class that extends `AdvancedFilterSet`.
        **meta: Additional metadata for customizing the filterset.

    Returns:
        A FilterSet class based on the provided parameters.
    """
    # If a base FilterSet class is provided, set it up for use with graphene
    if filterset_class:
        graphene_filterset_class = setup_filterset(filterset_class)
    # If no base class is provided, create a custom FilterSet class based on `AdvancedFilterSet`
    else:
        graphene_filterset_class = custom_filterset_factory(
            filterset_base_class=AdvancedFilterSet,
            **meta,
        )

    # Replace any comma-separated value (CSV) filters with a more flexible format
    replace_csv_filters(graphene_filterset_class)

    return graphene_filterset_class
