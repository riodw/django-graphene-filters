"""Functions for creating a FilterSet class."""

from typing import Any

from graphene_django.filter.filterset import custom_filterset_factory, setup_filterset
from graphene_django.filter.utils import replace_csv_filters

from .filterset import AdvancedFilterSet

_RESERVED_FACTORY_KEYS = {"filterset_base_class"}


# TODO(spec-base_type_naming.md): memoize the dynamic branch below.
# `custom_filterset_factory` fabricates a new AdvancedFilterSet subclass on
# every call; two connection fields using the same model without an
# explicit `filterset_class` would produce two distinct classes sharing the
# same `__name__` and trip class-based naming's collision check. Cache by
# `(model, frozenset(fields.items()))` so identical configs resolve to one
# class object. See spec §"Implementation plan" step 7.
def get_filterset_class(
    filterset_class: type[AdvancedFilterSet] | None,
    **meta: Any,
) -> type[AdvancedFilterSet]:
    """Return a FilterSet class for use in GraphQL queries.

    This function is a partial copy of the ``get_filterset_class`` function
    from graphene-django.

    Args:
        filterset_class: An optional base class that extends ``AdvancedFilterSet``.
        **meta: Additional metadata for customizing the filterset (e.g.
            ``model``, ``fields``).  Keys that collide with
            ``custom_filterset_factory``'s own parameters
            (``filterset_base_class``) are silently stripped to prevent
            ``TypeError: multiple values for keyword argument``.

            Note: ``model`` is required when ``filterset_class`` is ``None``.

    Returns:
        A FilterSet class based on the provided parameters.
    """
    # If a base FilterSet class is provided, set it up for use with graphene
    if filterset_class:
        graphene_filterset_class = setup_filterset(filterset_class)
    # If no base class is provided, create a custom FilterSet class based on `AdvancedFilterSet`
    else:
        # Strip reserved keys to prevent keyword collisions with
        # custom_filterset_factory(model, filterset_base_class=..., **meta).
        safe_meta = {k: v for k, v in meta.items() if k not in _RESERVED_FACTORY_KEYS}
        graphene_filterset_class = custom_filterset_factory(
            filterset_base_class=AdvancedFilterSet,
            **safe_meta,
        )

    # Replace any comma-separated value (CSV) filters with a more flexible format
    replace_csv_filters(graphene_filterset_class)

    return graphene_filterset_class
