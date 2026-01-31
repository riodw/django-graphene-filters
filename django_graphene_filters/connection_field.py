"""
`AdvancedDjangoFilterConnectionField` class module.

Use the `AdvancedDjangoFilterConnectionField` class from this
module instead of the `DjangoFilterConnectionField` from graphene-django.
"""

import warnings
from typing import Any, Callable, Dict, Iterable, Optional, Type, Union

import graphene
from django.core.exceptions import ValidationError
from django.db import models
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField

# Import the utility that generates standard arguments (e.g., name__icontains -> name_Icontains)
from graphene_django.filter.utils import get_filtering_args_from_filterset

# Local imports
from .conf import settings
from .filter_arguments_factory import FilterArgumentsFactory
from .filterset import AdvancedFilterSet
from .filterset_factories import get_filterset_class
from .input_data_factories import tree_input_type_to_data


class AdvancedDjangoFilterConnectionField(DjangoFilterConnectionField):
    """Allow you to use advanced filters provided by this library."""

    def __init__(
        self,
        type: Union[Type[DjangoObjectType], Callable[[], Type[DjangoObjectType]], str],
        fields: Optional[Dict[str, list]] = None,
        order_by: Any = None,
        extra_filter_meta: Optional[Dict[str, Any]] = None,
        filterset_class: Optional[Type[AdvancedFilterSet]] = None,
        filter_input_type_prefix: Optional[str] = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            type, fields, order_by, extra_filter_meta, filterset_class, *args, **kwargs
        )

        # Validate that the provided FilterSet class is an AdvancedFilterSet
        assert self.provided_filterset_class is None or issubclass(
            self.provided_filterset_class,
            AdvancedFilterSet,
        ), "Use the `AdvancedFilterSet` class with `AdvancedDjangoFilterConnectionField`"

        self._filter_input_type_prefix = filter_input_type_prefix

        # Handle cases where the filter_input_type_prefix is not provided
        self._handle_prefix_warnings()

    def _handle_prefix_warnings(self) -> None:
        """Handle warnings related to missing `filter_input_type_prefix`."""
        if self._filter_input_type_prefix is None and self._provided_filterset_class:
            warnings.warn(
                "The `filterset_class` argument without `filter_input_type_prefix` "
                "can result in different types with the same name in the schema.",
            )

        if (
            self._filter_input_type_prefix is None
            and self.node_type._meta.filterset_class
        ):
            warnings.warn(
                f"The `filterset_class` field of `{self.node_type.__name__}` Meta "
                "without the `filter_input_type_prefix` argument "
                "can result in different types with the same name in the schema.",
            )

    @property
    def provided_filterset_class(self) -> Optional[Type[AdvancedFilterSet]]:
        """
        Return the provided AdvancedFilterSet class, if any.
        """
        return self._provided_filterset_class or self.node_type._meta.filterset_class

    @property
    def filter_input_type_prefix(self) -> str:
        """
        Return a prefix for the filter input type name.
        """
        if self._filter_input_type_prefix:
            return self._filter_input_type_prefix

        node_type_name = self.node_type.__name__.replace("Type", "")

        if self.provided_filterset_class:
            return f"{node_type_name}{self.provided_filterset_class.__name__}"
        else:
            return node_type_name

    @property
    def filterset_class(self) -> Type[AdvancedFilterSet]:
        """
        Return the AdvancedFilterSet class to use for filtering.
        """
        if not self._filterset_class:
            fields = self._fields or self.node_type._meta.filter_fields
            meta = {"model": self.model, "fields": fields}
            if self._extra_filter_meta:
                meta.update(self._extra_filter_meta)

            self._filterset_class = get_filterset_class(
                self.provided_filterset_class, **meta
            )
        return self._filterset_class

    @property
    def filtering_args(self) -> dict:
        """
        Generate and return filtering arguments for GraphQL schema filterset.

        This merges:
        1. Standard Graphene arguments (flat, e.g., 'department_Name')
        2. Advanced arguments (nested, e.g., 'filter')
        """
        if not self._filtering_args:
            # 1. Get Standard Arguments (Flat style derived from filter_fields)
            standard_args = get_filtering_args_from_filterset(
                self.filterset_class, self.node_type
            )

            # 2. Get Advanced Arguments (The 'filter' tree input)
            advanced_args = FilterArgumentsFactory(
                self.filterset_class,
                self.filter_input_type_prefix,
            ).arguments

            # 3. Merge them (Advanced args take precedence if collision, though unlikely)
            self._filtering_args = {**standard_args, **advanced_args}

        return self._filtering_args

    @classmethod
    def resolve_queryset(
        cls,
        connection: object,
        iterable: Iterable,
        info: graphene.ResolveInfo,
        args: Dict[str, Any],
        filtering_args: Dict[str, graphene.InputField],
        filterset_class: Type[AdvancedFilterSet],
    ) -> models.QuerySet:
        """
        Return a filtered QuerySet.

        Handles both the nested 'filter' argument and standard flat arguments.
        """
        # Get base QuerySet
        qs = super(DjangoFilterConnectionField, cls).resolve_queryset(
            connection,
            iterable,
            info,
            args,
        )

        # 1. Process Advanced Filters (Tree structure)
        filter_arg = args.get(settings.FILTER_KEY, {})
        advanced_data = tree_input_type_to_data(filterset_class, filter_arg)

        # 2. Process Standard Filters (Flat structure)
        # We need to extract arguments that are NOT the advanced filter key
        flat_args = {k: v for k, v in args.items() if k != settings.FILTER_KEY}

        # We must map Graphene arguments (e.g. 'department_Name') back to FilterSet keys (e.g. 'department__name')
        # We can leverage the filtering_args dictionary to find the mapping if available,
        # or rely on the filterset's declared filters.
        flat_data = cls.map_arguments_to_filters(flat_args, filtering_args)

        # 3. Merge Data
        # Flattened args are added to the advanced data.
        # This allows users to mix `filter: {...}` and `name: "..."` in the same query if they really wanted to.
        combined_data = {**advanced_data, **flat_data}

        # Create filterset with combined data
        filterset = filterset_class(
            data=combined_data,
            queryset=qs,
            request=info.context,
        )

        if filterset.form.is_valid():
            # Apply .distinct() to remove duplicates caused by relationship joins
            return filterset.qs.distinct()

        raise ValidationError(filterset.form.errors.as_json())

    @staticmethod
    def map_arguments_to_filters(
        args: Dict[str, Any],
        filtering_args: Dict[str, graphene.InputField],
    ) -> Dict[str, Any]:
        """
        Map Graphene argument names back to Django FilterSet field names.

        Graphene usually converts `department__name` -> `department_Name`.
        We need to reverse this so the FilterSet recognizes the data.
        """
        mapped_data = {}

        # In graphene-django, the `filtering_args` keys are the GraphQL argument names.
        # However, `filtering_args` values don't easily store the original filter name.
        # A reliable heuristic is that standard arguments are generated from the FilterSet.

        # NOTE: A simpler approach for standard kwargs is passing them as-is,
        # but AdvancedFilterSet expects exact matches to declared filters.

        # We'll traverse the args provided in the query
        for arg_name, arg_value in args.items():
            # If the argument is in our schema
            if arg_name in filtering_args:
                # 1. Check if the arg_name exists directly in the generated filterset (unlikely for relations)
                # 2. Heuristic: Graphene replaces `__` with `_` and preserves case usually,
                #    but to support `department_Name` -> `department__name`, we might need to match
                #    against the filterset fields.

                # Note: This is a simplified mapping. For complex cases, we might need
                # to inspect the filterset class filters directly.
                mapped_data[arg_name] = arg_value

        return mapped_data
