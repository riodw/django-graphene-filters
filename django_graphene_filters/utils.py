from typing import List, Type

from django.db.models.constants import LOOKUP_SEP
from django.db.models.fields import Field
from django.db.models.expressions import Expression
from django.db.models.lookups import Transform


def lookups_for_field(model_field: Field) -> List[str]:
    """
    Generate a list of all possible lookup expressions for a given model field.

    Args:
        model_field: The model field for which to find lookup expressions.

    Returns:
        A list containing all lookup expressions applicable to the model field.
    """
    lookups: List[str] = []

    for expr, lookup in model_field.get_lookups().items():
        if issubclass(lookup, Transform):
            transform = lookup(Expression(model_field))
            lookups += [
                LOOKUP_SEP.join([expr, sub_expr])
                for sub_expr in lookups_for_transform(transform)
            ]
        else:
            lookups.append(expr)

    return lookups


def lookups_for_transform(transform: Transform) -> List[str]:
    """
    Generate a list of subsequent lookup expressions for a given transform.

    Note:
        Infinite transform recursion is prevented when the subsequent and passed-in
        transforms are the same class. For example, the `Unaccent` transform from
        `django.contrib.postgres`. No cycle detection across multiple transforms is
        implemented. For example, `a__b__a__b` would continue to recurse.
        However, this is not currently a problem (no builtin transforms exhibit this behavior).

    Args:
        transform: The transform for which to find lookup expressions.

    Returns:
        A list containing all lookup expressions applicable to the transform.
    """

    lookups: List[str] = []

    for expr, lookup in transform.output_field.get_lookups().items():
        if issubclass(lookup, Transform):
            # Skip if type matches to avoid infinite recursion
            if type(transform) == lookup:
                continue

            sub_transform = lookup(transform)
            lookups += [
                LOOKUP_SEP.join([expr, sub_expr])
                for sub_expr in lookups_for_transform(sub_transform)
            ]
        else:
            lookups.append(expr)

    return lookups
