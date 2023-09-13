"""
Utilities Module for Custom Django Filters.

This module provides utility functions designed to extend the capabilities of
the native Django-filter library, with specialized functions for handling field
lookups and transformations.

Functions
---------
- `lookups_for_field`: Determines the set of valid lookup expressions for a given model field.
- `lookups_for_transform`: Gets valid lookups for a given transform.

Usage
-----
```python
from .utils import lookups_for_field, lookups_for_transform

# Fetch valid lookup expressions for a CharField
lookups = lookups_for_field(models.CharField(), support_negation=True)

# Fetch valid lookup expressions for a given transform
transform_lookups = lookups_for_transform(models.Transform())
"""

from typing import List

from django.db.models.constants import LOOKUP_SEP
from django.db.models.expressions import Expression
from django.db.models.fields import Field
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
            if type(transform) is lookup:
                continue

            sub_transform = lookup(transform)
            lookups += [
                LOOKUP_SEP.join([expr, sub_expr])
                for sub_expr in lookups_for_transform(sub_transform)
            ]
        else:
            lookups.append(expr)

    return lookups
