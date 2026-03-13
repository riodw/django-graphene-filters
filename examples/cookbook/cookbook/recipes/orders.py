from graphql import GraphQLError

import django_graphene_filters as orders

from . import models


class ObjectTypeOrder(orders.AdvancedOrderSet):
    class Meta:
        model = models.ObjectType
        fields = "__all__"

    def check_name_permission(self, request):
        """Only staff users may order by ObjectType.name."""
        user = getattr(request, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("You must be a staff user to order by ObjectType name.")


class ObjectOrder(orders.AdvancedOrderSet):
    object_type = orders.RelatedOrder(
        ObjectTypeOrder,
        field_name="object_type",
        queryset=models.ObjectType.objects.all(),
    )
    # Relationships
    values = orders.RelatedOrder(
        "ValueOrder",
        field_name="values",
        queryset=models.Value.objects.all(),
    )

    class Meta:
        model = models.Object
        fields = "__all__"


class AttributeOrder(orders.AdvancedOrderSet):
    object_type = orders.RelatedOrder(
        ObjectTypeOrder,
        field_name="object_type",
        queryset=models.ObjectType.objects.all(),
    )

    class Meta:
        model = models.Attribute
        fields = "__all__"


class ValueOrder(orders.AdvancedOrderSet):
    attribute = orders.RelatedOrder(
        AttributeOrder,
        field_name="attribute",
        queryset=models.Attribute.objects.all(),
    )

    class Meta:
        model = models.Value
        fields = "__all__"
