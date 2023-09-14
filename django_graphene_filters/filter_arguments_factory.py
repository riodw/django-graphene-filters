"""Module for converting a AdvancedFilterSet class to filter arguments."""

from typing import Any, Callable, Dict, List, Optional, Sequence, Type, cast

import graphene
from anytree import Node
from django.db.models.constants import LOOKUP_SEP
from django_filters import Filter
from django_filters.conf import settings as django_settings
from graphene_django.filter.utils import get_model_field
from graphene_django.forms.converter import convert_form_field
from stringcase import pascalcase

from .conf import settings
from .filters import SearchQueryFilter, SearchRankFilter, TrigramFilter
from .filterset import AdvancedFilterSet
from .input_types import (
    SearchQueryFilterInputType,
    SearchRankFilterInputType,
    TrigramFilterInputType,
)


class FilterArgumentsFactory:
    """Factory for creating filter arguments in GraphQL from a given `AdvancedFilterSet` class."""

    # Special GraphQL filter input types and their associated factories
    SPECIAL_FILTER_INPUT_TYPES_FACTORIES: Dict[
        str, Callable[[], graphene.InputField]
    ] = {
        SearchQueryFilter.postfix: lambda: graphene.InputField(
            SearchQueryFilterInputType,
            description="Field for the full-text search using `SearchVector` and `SearchQuery` objects.",
        ),
        SearchRankFilter.postfix: lambda: graphene.InputField(
            SearchRankFilterInputType,
            description="Field for the full-text search using the `SearchRank` object.",
        ),
        TrigramFilter.postfix: lambda: graphene.InputField(
            TrigramFilterInputType,
            description="Field for the full-text search using trigram similarity or trigram distance.",
        ),
    }

    # Cache for storing input object types
    input_object_types: Dict[str, Type[graphene.InputObjectType]] = {}

    def __init__(
        self,
        filterset_class: Type[AdvancedFilterSet],
        input_type_prefix: str,
    ) -> None:
        """Initialize the factory with a filterset class and an input type prefix.

        Args:
            filterset_class: The AdvancedFilterSet class to convert.
            input_type_prefix: Prefix to use for GraphQL types.
        """
        self.filterset_class = filterset_class
        self.input_type_prefix = input_type_prefix
        self.filter_input_type_name = f"{self.input_type_prefix}FilterInputType"

    @property
    def arguments(self) -> Dict[str, graphene.Argument]:
        """
        Create and return the GraphQL arguments for filtering.

        Inspect a FilterSet and produce the arguments to pass to a Graphene Field.
        These arguments will be available to filter against in the GraphQL.

        Returns:
            A dictionary mapping from argument names to graphene.Argument objects.
        """
        input_object_type = self.input_object_types.get(
            self.filter_input_type_name,
            self.create_filter_input_type(
                self.filterset_to_trees(self.filterset_class),
            ),
        )
        return {
            settings.FILTER_KEY: graphene.Argument(
                input_object_type,
                description="Advanced filter field",
            ),
        }

    def create_filter_input_type(
        self, roots: List[Node]
    ) -> Type[graphene.InputObjectType]:
        """
        Generate a GraphQL filter InputObjectType for filtering based on the filter set trees.

        Args:
            roots: List of root nodes for each filter tree.

        Returns:
            A graphene.InputObjectType for filtering.
        """
        # Create GraphQL input fields based on the filter tree
        input_fields = {
            root.name: self.create_filter_input_subfield(
                root,
                self.input_type_prefix,
                f"`{pascalcase(root.name)}` field",
            )
            for root in roots
        }

        # Add special fields for AND, OR, and NOT fields for logical combination of filters
        logic_fields = {
            settings.AND_KEY: graphene.InputField(
                graphene.List(
                    lambda: self.input_object_types[self.filter_input_type_name]
                ),
                description="`And` field",
            ),
            settings.OR_KEY: graphene.InputField(
                graphene.List(
                    lambda: self.input_object_types[self.filter_input_type_name]
                ),
                description="`Or` field",
            ),
            settings.NOT_KEY: graphene.InputField(
                lambda: self.input_object_types[self.filter_input_type_name],
                description="`Not` field",
            ),
        }

        # Combine all fields and create the InputObjectType
        self.input_object_types[self.filter_input_type_name] = cast(
            Type[graphene.InputObjectType],
            type(
                self.filter_input_type_name,
                (graphene.InputObjectType,),
                {**input_fields, **logic_fields},
            ),
        )
        return self.input_object_types[self.filter_input_type_name]

    def create_filter_input_subfield(
        self,
        root: Node,
        prefix: str,
        description: str,
    ) -> graphene.InputField:
        """Create a filter input subfield from a filter set subtree."""
        if root.name in self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES:
            return self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES[root.name]()

        fields: Dict[str, graphene.InputField] = {}

        for child in root.children:
            if child.height == 0:
                filter_name = f"{LOOKUP_SEP}".join(
                    node.name
                    for node in child.path
                    if node.name != django_settings.DEFAULT_LOOKUP_EXPR
                )
                fields[child.name] = self.get_field(
                    filter_name, self.filterset_class.base_filters[filter_name]
                )
            else:
                fields[child.name] = self.create_filter_input_subfield(
                    child,
                    prefix + pascalcase(root.name),
                    f"`{pascalcase(child.name)}` subfield",
                )

        return graphene.InputField(
            self.create_input_object_type(
                f"{prefix}{pascalcase(root.name)}FilterInputType", fields
            ),
            description=description,
        )

    @classmethod
    def create_input_object_type(
        cls,
        name: str,
        fields: Dict[str, Any],
    ) -> Type[graphene.InputObjectType]:
        """Create a new GraphQL type inheritor inheriting from `graphene.InputObjectType` class."""
        # Use a cache to avoid creating the same InputObjectType again
        if name in cls.input_object_types:
            return cls.input_object_types[name]

        cls.input_object_types[name] = cast(
            Type[graphene.InputObjectType],
            type(
                name,
                (graphene.InputObjectType,),
                fields,
            ),
        )
        return cls.input_object_types[name]

    def get_field(self, name: str, filter_obj: Filter) -> graphene.InputField:
        """
        Create and return a Graphene input field from a Django Filter field.

        Parameters:
        - name (str): The name of the field.
        - filter_obj (Filter): The Django Filter field.

        Returns:
        - graphene.InputField: The created Graphene input field.
        """
        model = self.filterset_class._meta.model
        filter_type: str = filter_obj.lookup_expr

        # Initialize form field directly from the filter_obj filter
        form_field = filter_obj.field

        # Handle special case when the filter_obj filter type is not 'isnull' and the name is not declared
        if filter_type != "isnull" and name not in getattr(
            self.filterset_class, "declared_filters"
        ):
            model_field = get_model_field(model, filter_obj.field_name)
            if hasattr(model_field, "formfield"):
                form_field = model_field.formfield(
                    required=filter_obj.extra.get("required", False)
                )

        # Convert Django form field to Graphene field
        graphene_field = convert_form_field(form_field)

        if filter_type in ("in", "range"):
            graphene_field = graphene.List(graphene_field.get_type())

        field_type = graphene_field.InputField()
        field_type.description = getattr(
            filter_obj, "label", f"`{pascalcase(filter_obj.lookup_expr)}` lookup"
        )
        return field_type

    @classmethod
    def filterset_to_trees(cls, filterset_class: Type[AdvancedFilterSet]) -> List[Node]:
        """
        Convert a FilterSet class to a list of trees.

        where each tree represents a set of chained lookups for a filter.

        Parameters:
        - filterset_class (Type[AdvancedFilterSet]): The FilterSet class to be converted.

        Returns:
        - List[Node]: A list of root nodes for each tree, each representing a filter.
        """
        # Initialize an empty list to hold the root nodes of the trees.
        trees: List[Node] = []

        # Iterate through each filter in the FilterSet's base_filters.
        for filter_value in filterset_class.base_filters.values():
            # Split the filter's field_name and lookup_expr into a sequence of values.
            values = (
                *filter_value.field_name.split(LOOKUP_SEP),
                filter_value.lookup_expr,
            )

            # Check if any existing tree can accommodate the new sequence of values.
            # If not, create a new tree for it.
            if not trees or not any(
                cls.try_add_sequence(tree, values) for tree in trees
            ):
                trees.append(cls.sequence_to_tree(values))

        return trees

    @classmethod
    def try_add_sequence(cls, root: Node, values: Sequence[str]) -> bool:
        """
        Attempt to add a sequence of values to an existing tree rooted at `root`.

        Return a flag indicating whether the mutation was made.

        Parameters:
        - root (Node): The root node of the tree.
        - values (Sequence[str]): The sequence of values to add.

        Returns:
        - bool: True if the sequence was successfully added, otherwise False.
        """
        if root.name != values[0]:
            return False

        for child in root.children:
            # is mutated?
            if cls.try_add_sequence(child, values[1:]):
                return True
        # Add a new subtree rooted at `root` if the sequence could not be added to any child
        root.children = (*root.children, cls.sequence_to_tree(values[1:]))
        return True

    @staticmethod
    def sequence_to_tree(values: Sequence[str]) -> Node:
        """
        Convert a sequence of values into a tree, where each value becomes a node.

        Parameters:
        - values (Sequence[str]): The sequence of values.

        Returns:
        - Node: The root node of the generated tree.
        """
        node: Optional[Node] = None

        for value in values:
            node = Node(name=value, parent=node)

        return node.root
