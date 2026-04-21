"""Utilities for field lookup, transform discovery, and class-based naming.

Functions
---------
- ``lookups_for_field``: All valid lookup expressions for a model field.
- ``lookups_for_transform``: Subsequent lookups for a given transform.
- ``raise_on_type_name_collision``: Guard shared by the three argument
  factories to enforce class-based GraphQL naming.

Usage
-----
```python
from .utils import lookups_for_field

# e.g. ['exact', 'icontains', 'gt', 'date', 'date__exact', 'date__lt', ...]
lookups = lookups_for_field(MyModel._meta.get_field("created"))
```
"""

from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import Expression
from django.db.models.fields import Field
from django.db.models.lookups import Transform


def raise_on_type_name_collision(
    type_name: str,
    cls: type,
    registry: dict[str, type],
    kind: str,
) -> None:
    """Raise ``TypeError`` if ``type_name`` is already claimed by a different class.

    Shared by ``FilterArgumentsFactory`` / ``OrderArgumentsFactory`` /
    ``AggregateArgumentsFactory`` to enforce class-based GraphQL naming
    (see ``docs/spec-base_type_naming.md``): two distinct Python classes
    with the same ``__name__`` would otherwise silently overwrite each
    other's schema.

    Args:
        type_name: The GraphQL type name being claimed.
        cls: The Python class claiming the name on this call.
        registry: Factory-level ``name -> declaring_class`` map.
        kind: Human-readable label (``"filterset"`` / ``"orderset"`` /
            ``"aggregateset"``) used in the error message.
    """
    prior = registry.get(type_name)
    if prior is not None and prior is not cls:
        raise TypeError(
            f"Class-based naming collision: GraphQL type '{type_name}' is already "
            f"registered by '{prior.__module__}.{prior.__qualname__}' but now "
            f"'{cls.__module__}.{cls.__qualname__}' is trying to claim "
            f"the same name. Rename one of the {kind} classes."
        )


def lookups_for_field(model_field: Field) -> list[str]:
    """Generate a list of all possible lookup expressions for a given model field.

    Transform lookups are included in two forms:

    * **Bare** (e.g. ``date``) — equivalent to the implicit ``__exact`` on the
      transform's output field (``created__date=today`` is valid ORM shorthand
      for ``created__date__exact=today``).
    * **Expanded** (e.g. ``date__exact``, ``date__lt``) — explicit sub-lookups.

    Args:
        model_field: The model field for which to find lookup expressions.

    Returns:
        A list containing all lookup expressions applicable to the model field.
    """
    lookups: list[str] = []

    for expr, lookup in model_field.get_lookups().items():
        if issubclass(lookup, Transform):
            transform = lookup(Expression(model_field))
            # Include the bare transform itself (implicit __exact on output field).
            lookups.append(expr)
            lookups += [LOOKUP_SEP.join([expr, sub_expr]) for sub_expr in lookups_for_transform(transform)]
        else:
            lookups.append(expr)

    return lookups


def lookups_for_transform(
    transform: Transform,
    _visited: frozenset[type[Transform]] = frozenset(),
) -> list[str]:
    """Generate a list of subsequent lookup expressions for a given transform.

    Lookups are collected from two sources and merged:

    * ``transform.output_field.get_lookups()`` — the standard lookups available
      on the transform's output field type.
    * ``type(transform).get_lookups()`` — lookups registered directly on the
      transform class itself (e.g. via ``MyTransform.register_lookup(...)``),
      such as custom or third-party transforms that expose extra operators.
      These take precedence over output-field lookups on name collisions.

    Sub-transform lookups are included in bare form (implicit ``__exact``) as
    well as expanded form (e.g. ``sub__exact``, ``sub__lt``).

    Cycle detection via a visited-class set prevents infinite recursion in both
    direct self-loops (e.g. the ``Unaccent`` transform from
    ``django.contrib.postgres`` registered on its own output field) and
    multi-step cycles (e.g. ``a__b__a__b__…``). Any transform class already
    present in the current recursion chain is skipped.

    Args:
        transform: The transform for which to find lookup expressions.
        _visited: Internal — frozenset of transform classes already in the
            current recursion chain. Callers should not pass this argument.

    Returns:
        A list containing all lookup expressions applicable to the transform.
    """
    lookups: list[str] = []
    _visited = _visited | {type(transform)}

    # Merge output_field lookups with any lookups registered directly on the
    # transform class (e.g. `MyTransform.register_lookup(SomeLookup)`).
    # Transform-own entries take precedence on name collisions.
    all_lookups = {**transform.output_field.get_lookups(), **type(transform).get_lookups()}

    for expr, lookup in all_lookups.items():
        if issubclass(lookup, Transform):
            # Skip if this Transform class is already in the chain — catches both
            # direct self-loops and multi-step cycles (a__b__a__b…).
            if lookup in _visited:
                continue

            sub_transform = lookup(transform)
            # Include the bare sub-transform itself (implicit __exact on its output field).
            lookups.append(expr)
            lookups += [
                LOOKUP_SEP.join([expr, sub_expr])
                for sub_expr in lookups_for_transform(sub_transform, _visited)
            ]
        else:
            lookups.append(expr)

    return lookups
