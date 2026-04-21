"""Functions for creating a FilterSet class."""

from typing import Any

from graphene_django.filter.filterset import custom_filterset_factory
from graphene_django.filter.utils import replace_csv_filters

from .filterset import AdvancedFilterSet

_RESERVED_FACTORY_KEYS = {"filterset_base_class"}

# Memoizes dynamically-generated AdvancedFilterSet subclasses by (model, fields).
# Under class-based naming, two connection fields on the same model (without an
# explicit ``filterset_class``) would otherwise fabricate two distinct classes
# sharing the same ``__name__`` and trip the collision check in
# ``FilterArgumentsFactory``.  Caching here guarantees identical configs resolve
# to the same class object.  See ``docs/spec-base_type_naming.md``.
_dynamic_filterset_cache: dict[Any, type[AdvancedFilterSet]] = {}


def _make_cache_key(safe_meta: dict[str, Any]) -> Any:
    """Build a hashable cache key from the meta dict.

    ``model`` is the primary discriminator.  ``fields`` may be ``"__all__"``,
    a list of field names, or a dict mapping field -> list of lookups — all
    serialised into a hashable form so identical declarations share a class.
    Any extra meta keys are included verbatim (they are flags like
    ``interfaces`` or ``exclude``).
    """
    model = safe_meta.get("model")
    fields = safe_meta.get("fields")
    if isinstance(fields, dict):
        fields_key = (
            "dict",
            tuple(sorted((k, tuple(v) if isinstance(v, list) else v) for k, v in fields.items())),
        )
    elif isinstance(fields, (list, tuple)):
        fields_key = ("seq", tuple(fields))
    else:
        fields_key = ("raw", fields)
    extra = tuple(sorted((k, v) for k, v in safe_meta.items() if k not in {"model", "fields"}))
    return (model, fields_key, extra)


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
    # If a base FilterSet class is provided, use it directly.  ``AdvancedFilterSet``
    # subclasses inherit ``GrapheneFilterSetMixin`` for ``FILTER_DEFAULTS`` (the
    # GlobalIDFilter overrides on FKs/PKs), so graphene-django's ``setup_filterset``
    # wrapper is unnecessary — it would only produce a divergent
    # ``Graphene{X}Filter`` class name that breaks class-based naming (see
    # ``docs/spec-base_type_naming.md``).  ``AdvancedDjangoFilterConnectionField``
    # validates the subclass upfront; this function trusts its caller.
    if filterset_class is not None:
        graphene_filterset_class = filterset_class
    # If no base class is provided, create a custom FilterSet class based on `AdvancedFilterSet`
    else:
        # Strip reserved keys to prevent keyword collisions with
        # custom_filterset_factory(model, filterset_base_class=..., **meta).
        safe_meta = {k: v for k, v in meta.items() if k not in _RESERVED_FACTORY_KEYS}
        cache_key = _make_cache_key(safe_meta)
        cached = _dynamic_filterset_cache.get(cache_key)
        if cached is not None:
            graphene_filterset_class = cached
        else:
            graphene_filterset_class = custom_filterset_factory(
                filterset_base_class=AdvancedFilterSet,
                **safe_meta,
            )
            _dynamic_filterset_cache[cache_key] = graphene_filterset_class

    # Replace any comma-separated value (CSV) filters with a more flexible format
    replace_csv_filters(graphene_filterset_class)

    return graphene_filterset_class
