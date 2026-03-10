"""Module for converting a AdvancedOrderSet class to ordering arguments."""

import graphene

from .mixins import InputObjectTypeFactoryMixin


class OrderDirection(graphene.Enum):
    """Enum to represent the sorting direction of a field."""

    ASC = "asc"
    DESC = "desc"


class OrderArgumentsFactory(InputObjectTypeFactoryMixin):
    """Factory for creating ordering arguments in GraphQL from an AdvancedOrderSet class."""

    def __init__(
        self,
        orderset_class,
        input_type_prefix: str,
    ) -> None:
        """Initialize the factory with an orderset class and an input type prefix."""
        self.orderset_class = orderset_class
        self.input_type_prefix = input_type_prefix
        self.order_input_type_name = f"{self.input_type_prefix}OrderInputType"

    @property
    def arguments(self) -> dict[str, graphene.Argument]:
        """Create and return the GraphQL arguments for ordering."""
        input_object_type = self.create_order_input_type()
        return {
            "orderBy": graphene.Argument(
                graphene.List(graphene.NonNull(input_object_type)),
                description="Advanced ordering field (array of objects for priority matching)",
            ),
        }

    def create_order_input_type(self, orderset_class=None, prefix=None) -> type[graphene.InputObjectType]:
        """Dynamically build nested GraphQL InputObjectTypes based on relationships."""
        orderset_class = orderset_class or self.orderset_class
        prefix = prefix or self.input_type_prefix
        type_name = f"{prefix}OrderInputType"

        if type_name in type(self).input_object_types:
            return type(self).input_object_types[type_name]

        fields = {}
        # Fetch the available ordering fields from the Meta class and RelatedOrders
        for field_name, related_order in orderset_class.get_fields().items():
            if related_order:
                # Relationship traversal
                sub_prefix = f"{prefix}{field_name.capitalize()}"
                target_orderset = related_order.orderset
                if target_orderset:
                    sub_type = self.create_order_input_type(target_orderset, sub_prefix)
                    fields[field_name] = graphene.InputField(sub_type)
            else:
                # Flat field (no traversal, leaf node)
                fields[field_name] = graphene.InputField(OrderDirection)

        return type(self).create_input_object_type(type_name, fields)
