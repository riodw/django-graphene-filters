"""Module for converting an AdvancedAggregateSet class to aggregate output types."""

import graphene
from stringcase import pascalcase

from .aggregate_types import STAT_TYPES
from .aggregateset import AdvancedAggregateSet
from .mixins import ObjectTypeFactoryMixin


class AggregateArgumentsFactory(ObjectTypeFactoryMixin):
    """Factory for creating aggregate output types in GraphQL from an AdvancedAggregateSet class.

    Analogous to ``FilterArgumentsFactory`` / ``OrderArgumentsFactory``, but generates
    output ``ObjectType`` classes (not ``InputObjectType``) since aggregates are returned
    in the response, not passed as arguments.
    """

    # Track which aggregate classes are currently being built to prevent infinite recursion
    # from circular RelatedAggregate references (e.g. ObjectAggregate → ValueAggregate → ObjectAggregate)
    _building: set[type] = set()

    def __init__(
        self,
        aggregate_class: type[AdvancedAggregateSet],
        input_type_prefix: str,
    ) -> None:
        """Initialize the factory.

        Args:
            aggregate_class: The AdvancedAggregateSet class to convert.
            input_type_prefix: Prefix for generated GraphQL type names.
        """
        self.aggregate_class = aggregate_class
        self.input_type_prefix = input_type_prefix

    def build_aggregate_type(self) -> type[graphene.ObjectType]:
        """Build the root aggregate ObjectType.

        For an ObjectAggregate with fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
            "created_date": ["min", "max"],
        }

        Generates::

            class ObjectAggregateType(ObjectType):
                count = Int()
                name = Field(ObjectNameAggregateType)
                created_date = Field(ObjectCreatedDateAggregateType)

            class ObjectNameAggregateType(ObjectType):
                count = Int()
                min = String()
                max = String()
                mode = String()
                uniques = List(UniqueValueType)

            class ObjectCreatedDateAggregateType(ObjectType):
                min = DateTime()
                max = DateTime()

        Returns:
            The root aggregate ObjectType class.
        """
        config = self.aggregate_class._aggregate_config
        custom_stats = self.aggregate_class._custom_stats

        # Root-level count is always present
        root_fields: dict[str, graphene.Field | graphene.Scalar] = {
            "count": graphene.Int(description="Total number of records in the filtered result set"),
        }

        for field_name, field_config in config.items():
            category = field_config["category"]
            stat_names = field_config["stats"]

            # Build per-field sub-type
            sub_fields = self._build_stat_fields(category, stat_names, custom_stats)
            sub_type_name = f"{self.input_type_prefix}{pascalcase(field_name)}AggregateType"
            sub_type = self.create_object_type(sub_type_name, sub_fields)

            root_fields[field_name] = graphene.Field(
                sub_type,
                description=f"Aggregate statistics for `{field_name}`",
            )

        # Build nested types for RelatedAggregates (with recursion protection)
        AggregateArgumentsFactory._building.add(self.aggregate_class)
        try:
            for rel_name, rel_agg in getattr(self.aggregate_class, "related_aggregates", {}).items():
                target_class = rel_agg.aggregate_class
                if target_class in AggregateArgumentsFactory._building:
                    # Circular reference — skip to prevent infinite recursion
                    continue
                child_prefix = f"{self.input_type_prefix}{pascalcase(rel_name)}"
                child_factory = AggregateArgumentsFactory(target_class, child_prefix)
                child_type = child_factory.build_aggregate_type()
                root_fields[rel_name] = graphene.Field(
                    child_type,
                    description=f"Aggregates across `{rel_name}` relationship",
                )
        finally:
            AggregateArgumentsFactory._building.discard(self.aggregate_class)

        root_type_name = f"{self.input_type_prefix}AggregateType"
        return self.create_object_type(root_type_name, root_fields)

    @staticmethod
    def _build_stat_fields(
        category: str,
        stat_names: list[str],
        custom_stats: dict,
    ) -> dict[str, graphene.Scalar | graphene.List]:
        """Build the graphene fields for a set of stat names.

        Args:
            category: The field category ('text', 'numeric', 'datetime', 'boolean').
            stat_names: List of stat names to include.
            custom_stats: Custom stat name -> graphene type mapping.

        Returns:
            A dict of {stat_name: graphene_field_instance}.
        """
        fields: dict = {}
        category_types = STAT_TYPES.get(category, {})

        for stat_name in stat_names:
            if stat_name in custom_stats:
                # Custom stat — type provided by the consumer
                gql_type = custom_stats[stat_name]
                fields[stat_name] = gql_type(description=f"Custom stat: `{stat_name}`")
            elif stat_name in category_types:
                # Built-in stat — type from STAT_TYPES registry
                gql_type = category_types[stat_name]
                if isinstance(gql_type, graphene.List):
                    # Already instantiated (e.g. List(UniqueValueType))
                    fields[stat_name] = graphene.Field(
                        gql_type,
                        description=f"`{stat_name}` stat",
                    )
                else:
                    fields[stat_name] = gql_type(description=f"`{stat_name}` stat")

        return fields
