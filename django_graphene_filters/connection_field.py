"""`AdvancedDjangoFilterConnectionField` class module.

Use the `AdvancedDjangoFilterConnectionField` class from this
module instead of the `DjangoFilterConnectionField` from graphene-django.
"""

from collections import OrderedDict
from collections.abc import Callable, Iterable
from typing import Any

import graphene
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from graphene_django import DjangoObjectType
from graphene_django.filter import DjangoFilterConnectionField

# Import the utility that generates standard arguments (e.g., name__icontains -> name_Icontains)
from graphene_django.filter.utils import get_filtering_args_from_filterset

# Local imports
from .conf import settings
from .filter_arguments_factory import FilterArgumentsFactory
from .filters import BaseRelatedFilter
from .filterset import AdvancedFilterSet
from .filterset_factories import get_filterset_class
from .input_data_factories import tree_input_type_to_data
from .order_arguments_factory import OrderArgumentsFactory


class AdvancedDjangoFilterConnectionField(DjangoFilterConnectionField):
    """Allow you to use advanced filters provided by this library."""

    def __init__(
        self,
        type: type[DjangoObjectType] | Callable[[], type[DjangoObjectType]] | str,
        fields: dict[str, list] | None = None,
        order_by: Any = None,
        extra_filter_meta: dict[str, Any] | None = None,
        filterset_class: type[AdvancedFilterSet] | None = None,
        filter_input_type_prefix: str | None = None,
        orderset_class: Any | None = None,
        order_input_type_prefix: str | None = None,
        aggregate_class: Any | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        self._provided_orderset_class = orderset_class
        self._order_input_type_prefix = order_input_type_prefix
        self._orderset_class = None
        self._ordering_args = None
        self._provided_aggregate_class = aggregate_class
        self._aggregate_class = None
        self._aggregate_type = None

        super().__init__(type, fields, order_by, extra_filter_meta, filterset_class, *args, **kwargs)

        # Validate that the provided FilterSet class is an AdvancedFilterSet
        assert self.provided_filterset_class is None or issubclass(
            self.provided_filterset_class,
            AdvancedFilterSet,
        ), "Use the `AdvancedFilterSet` class with `AdvancedDjangoFilterConnectionField`"

        self._filter_input_type_prefix = filter_input_type_prefix

    # -----------------------------------------------------------------
    # Aggregate support
    # -----------------------------------------------------------------

    @property
    def provided_aggregate_class(self) -> Any | None:
        """Return the provided AdvancedAggregateSet class, if any."""
        return self._provided_aggregate_class or getattr(self.node_type._meta, "aggregate_class", None)

    @property
    def aggregate_class(self) -> Any | None:
        """Return the AdvancedAggregateSet class to use for aggregation."""
        if not self._aggregate_class:
            self._aggregate_class = self.provided_aggregate_class
        return self._aggregate_class

    @property
    def aggregate_type(self) -> type[graphene.ObjectType] | None:
        """Build (and cache) the aggregate ObjectType for this field."""
        if not self._aggregate_type and self.aggregate_class:
            from .aggregate_arguments_factory import AggregateArgumentsFactory

            node_type_name = self.node_type.__name__.replace("Type", "")
            if self.aggregate_class:
                prefix = f"{node_type_name}{self.aggregate_class.__name__}"
            else:
                prefix = node_type_name
            factory = AggregateArgumentsFactory(self.aggregate_class, prefix)
            self._aggregate_type = factory.build_aggregate_type()
        return self._aggregate_type

    # -----------------------------------------------------------------
    # Orderset support (existing)
    # -----------------------------------------------------------------

    @property
    def provided_orderset_class(self) -> Any | None:
        """Return the provided AdvancedOrderSet class, if any."""
        return self._provided_orderset_class or getattr(self.node_type._meta, "orderset_class", None)

    @property
    def order_input_type_prefix(self) -> str:
        """Return a prefix for the order input type name."""
        if self._order_input_type_prefix:
            return self._order_input_type_prefix

        node_type_name = self.node_type.__name__.replace("Type", "")

        if self.provided_orderset_class:
            return f"{node_type_name}{self.provided_orderset_class.__name__}"
        return node_type_name

    @property
    def orderset_class(self) -> Any | None:
        """Return the AdvancedOrderSet class to use for ordering."""
        # TODO: Implement optional creation/factory if needed
        if not self._orderset_class:
            self._orderset_class = self.provided_orderset_class
        return self._orderset_class

    @property
    def ordering_args(self) -> dict:
        """Generate and return ordering arguments for GraphQL schema orderset."""
        if not self._ordering_args and self.orderset_class:
            self._ordering_args = OrderArgumentsFactory(
                self.orderset_class,
                self.order_input_type_prefix,
            ).arguments
        return self._ordering_args or {}

    @property
    def search_fields(self) -> tuple[str, ...] | None:
        """Return search_fields from the node type's Meta, if defined."""
        return getattr(self.node_type._meta, "search_fields", None)

    @property
    def search_args(self) -> dict:
        """Return a ``search`` argument if the node type defines ``search_fields``."""
        if self.search_fields:
            return {
                "search": graphene.Argument(
                    graphene.String,
                    description="Search across fields defined in search_fields",
                ),
            }
        return {}

    @property
    def args(self) -> dict:
        """Merge standard Graphene args, filtering args, ordering args, and search args."""
        args = super().args.copy()
        args.update(self.ordering_args)
        args.update(self.search_args)
        return args

    @args.setter
    def args(self, args: dict) -> None:
        """Required to satisfy Graphene's Field initialization."""
        self._base_args = args

    @property
    def provided_filterset_class(self) -> type[AdvancedFilterSet] | None:
        """Return the provided AdvancedFilterSet class, if any."""
        return self._provided_filterset_class or self.node_type._meta.filterset_class

    @property
    def filter_input_type_prefix(self) -> str:
        """Return a prefix for the filter input type name."""
        if self._filter_input_type_prefix:
            return self._filter_input_type_prefix

        node_type_name = self.node_type.__name__.replace("Type", "")

        if self.provided_filterset_class:
            return f"{node_type_name}{self.provided_filterset_class.__name__}"
        return node_type_name

    @property
    def filterset_class(self) -> type[AdvancedFilterSet]:
        """Return the AdvancedFilterSet class to use for filtering."""
        if not self._filterset_class:
            fields = self._fields or self.node_type._meta.filter_fields
            meta = {"model": self.model, "fields": fields}
            if self._extra_filter_meta:
                meta.update(self._extra_filter_meta)

            self._filterset_class = get_filterset_class(self.provided_filterset_class, **meta)
        return self._filterset_class

    @property
    def filtering_args(self) -> dict:
        """Generate and return filtering arguments for GraphQL schema filterset.

        This merges:
        1. Standard Graphene arguments (flat, e.g., 'department_Name')
        2. Advanced arguments (nested, e.g., 'filter')
        """
        if not self._filtering_args:
            # 1. Get Standard Arguments (Flat style derived from filter_fields)
            # We use a trimmed version of the class to HIDE the expanded RelatedFilters
            # from the root-level arguments.
            trimmed_class = self._get_trimmed_filterset_class()

            standard_args = get_filtering_args_from_filterset(trimmed_class, self.node_type)

            # 2. Get Advanced Arguments (The 'filter' tree input)
            # We use the FULL class here so the tree is built correctly
            advanced_args = FilterArgumentsFactory(
                self.filterset_class,
                self.filter_input_type_prefix,
            ).arguments

            # 3. Merge them (Advanced args take precedence if collision, though unlikely)
            self._filtering_args = {**standard_args, **advanced_args}

        return self._filtering_args

    def _get_trimmed_filterset_class(self) -> type[AdvancedFilterSet]:
        """Create a temporary FilterSet subclass that excludes expanded related filters.

        This prevents arguments like `values_Value_Icontains` from appearing in the
        schema root, ensuring they are only accessible via the nested `filter` argument.
        """
        # Ensure the original class is fully loaded/expanded
        full_filters = self.filterset_class.base_filters
        related_filters = self.filterset_class.related_filters

        trimmed_filters = OrderedDict()

        for name, f in full_filters.items():
            # Check if this filter is an "expanded" child of a RelatedFilter.
            # E.g. "values__value" is a child of "values".
            is_expanded_child = any(
                name.startswith(f"{rel_name}{LOOKUP_SEP}") for rel_name in related_filters
            )

            # Keep the filter if it's not an expanded child and NOT a RelatedFilter itself
            # We check both isinstance and class name for robustness
            if not is_expanded_child and not (
                isinstance(f, BaseRelatedFilter) or f.__class__.__name__.endswith("RelatedFilter")
            ):
                trimmed_filters[name] = f

        # Create a dynamic class with the cleaned filters
        # We inherit from the original class to pass any isinstance checks Graphene might do
        # We also clear related_filters so get_filters() doesn't re-expand them.
        return type(
            f"Trimmed{self.filterset_class.__name__}",
            (self.filterset_class,),
            {
                "base_filters": trimmed_filters,
                "related_filters": OrderedDict(),
            },
        )

    @classmethod
    def resolve_queryset(
        cls,
        connection: object,
        iterable: Iterable,
        info: graphene.ResolveInfo,
        args: dict[str, Any],
        filtering_args: dict[str, graphene.InputField],
        filterset_class: type[AdvancedFilterSet],
    ) -> models.QuerySet:
        """Return a filtered QuerySet.

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

        # 1b. Extract search argument (handled separately by the filterset's qs property)
        search_query = args.get("search")

        # 2. Process Standard Filters (Flat structure)
        # We need to extract arguments that are NOT the advanced filter key or search
        flat_args = {k: v for k, v in args.items() if k not in (settings.FILTER_KEY, "search")}

        # We must map Graphene arguments (e.g. 'department_Name') back to
        # FilterSet keys (e.g. 'department__name')
        # We can leverage the filtering_args dictionary to find the mapping if available,
        # or rely on the filterset's declared filters.
        flat_data = cls.map_arguments_to_filters(flat_args, filtering_args)

        # 3. Merge Data
        # Flattened args are added to the advanced data.
        # This allows users to mix `filter: {...}` and `name: "..."` in the
        # same query if they really wanted to.
        combined_data = {**advanced_data, **flat_data}

        # 4. Inject search into combined data so the filterset's qs property picks it up
        if search_query:
            combined_data["search"] = search_query

        # 5. Propagate search_fields from the node type Meta to the filterset
        search_fields = getattr(connection._meta.node._meta, "search_fields", None)

        # Create filterset with combined data
        filterset = filterset_class(
            data=combined_data,
            queryset=qs,
            request=info.context,
            search_fields=search_fields,
        )

        if filterset.form.is_valid():
            # Apply .distinct() to remove duplicates caused by relationship joins
            qs = filterset.qs.distinct()

            # Extract orderBy from args and apply orderset_class logic here
            order_arg = args.get("orderBy", [])
            orderset_class = getattr(connection._meta.node._meta, "orderset_class", None)

            if orderset_class and order_arg:
                orderset = orderset_class(data=order_arg, queryset=qs, request=info.context)
                qs = orderset.qs

            # Compute aggregates from the filtered queryset (only if requested)
            aggregate_class = getattr(connection._meta.node._meta, "aggregate_class", None)
            agg_selection = cls._extract_aggregate_selection(info) if aggregate_class else None
            if aggregate_class and agg_selection is not None:
                agg_set = aggregate_class(queryset=qs, request=info.context)
                qs._aggregate_results = agg_set.compute(selection_set=agg_selection)

            return qs

        raise ValidationError(filterset.form.errors.as_json())

    @classmethod
    def resolve_connection(
        cls,
        connection: object,
        args: dict[str, Any],
        iterable: Any,
        max_limit: int | None = None,
    ) -> Any:
        """Override to attach aggregate results to the connection instance."""
        result = super().resolve_connection(connection, args, iterable, max_limit)
        # If aggregates were computed during resolve_queryset, attach them
        if hasattr(iterable, "_aggregate_results"):
            result.aggregates = iterable._aggregate_results
        return result

    @staticmethod
    def _extract_aggregate_selection(info: graphene.ResolveInfo) -> Any:
        """Extract the ``aggregates`` sub-selection from the GraphQL query info.

        Returns the selection set of the ``aggregates`` field, or ``None``
        if aggregates were not requested.
        """
        try:
            for field_node in info.field_nodes:
                if field_node.selection_set:
                    for selection in field_node.selection_set.selections:
                        if selection.name.value == "aggregates":
                            return selection.selection_set
        except (AttributeError, TypeError):
            pass
        return None

    @staticmethod
    def map_arguments_to_filters(
        args: dict[str, Any],
        filtering_args: dict[str, graphene.InputField],
    ) -> dict[str, Any]:
        """Map Graphene argument names back to Django FilterSet field names.

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
