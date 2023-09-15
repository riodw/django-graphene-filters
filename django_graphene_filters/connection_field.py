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

        The method looks for a provided filterset class in two places:
        1. An explicitly provided `_provided_filterset_class` attribute.
        2. The `filterset_class` field in the `Meta` class of the `node_type`.

        Returns:
            The AdvancedFilterSet class if found, otherwise None.
        """
        return self._provided_filterset_class or self.node_type._meta.filterset_class

    @property
    def filter_input_type_prefix(self) -> str:
        """
        Return a prefix for the filter input type name.

        The prefix is determined based on the following:
        1. If `_filter_input_type_prefix` is set, use it as the prefix.
        2. If a `provided_filterset_class` exists, concatenate its name with the `node_type` name.
        3. Otherwise, use the `node_type` name.

        Returns:
            A string that will be used as the prefix for the filter input type.
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

        The method dynamically generates a filterset class if one isn't already set.
        It first checks if `_filterset_class` is already defined. If not, it proceeds
        to create one using the `get_filterset_class` function.

        Returns:
            A class inheriting from AdvancedFilterSet to be used for filtering the queryset.
        """
        if not self._filterset_class:
            # Obtain the fields for filtering, either from explicit setting or node's Meta class
            fields = self._fields or self.node_type._meta.filter_fields

            # Prepare the meta information needed for creating the filterset class
            meta = {"model": self.model, "fields": fields}

            # If extra filter metadata is provided, update the meta dictionary
            if self._extra_filter_meta:
                meta.update(self._extra_filter_meta)

            # Generate the filterset class dynamically
            self._filterset_class = get_filterset_class(
                self.provided_filterset_class, **meta
            )
        return self._filterset_class

    @property
    def filtering_args(self) -> dict:
        """Generate and return filtering arguments for GraphQL schema filterset.

        The arguments are dynamically generated based on the filterset class and a prefix.
        The `FilterArgumentsFactory` is used for this generation.

        Returns:
            A dictionary representing the filtering arguments for GraphQL schema.
        """
        if not self._filtering_args:
            # Dynamically generate the filtering arguments using FilterArgumentsFactory
            self._filtering_args = FilterArgumentsFactory(
                self.filterset_class,
                self.filter_input_type_prefix,
            ).arguments

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
        """Return a filtered QuerySet.

        Args:
            connection: The GraphQL Connection object.
            iterable: The original iterable data source.
            info: The GraphQL query info.
            args: Arguments passed in the GraphQL query.
            filtering_args: Defined filtering arguments.
            filterset_class: The filterset class to use for filtering.

        Returns:
            A filtered QuerySet.

        Raises:
            ValidationError: If the filterset form is invalid.
        """
        # Use parent class method to get the initial QuerySet
        qs = super(DjangoFilterConnectionField, cls).resolve_queryset(
            connection,
            iterable,
            info,
            args,
        )
        # Retrieve the filter arguments from the query
        filter_arg = args.get(settings.FILTER_KEY, {})
        # Create a filterset with the query arguments
        filterset = filterset_class(
            data=tree_input_type_to_data(filterset_class, filter_arg),
            queryset=qs,
            request=info.context,
        )

        # Validate and apply the filters
        if filterset.form.is_valid():
            return filterset.qs

        # Raise an error if the form is invalid
        raise ValidationError(filterset.form.errors.as_json())
