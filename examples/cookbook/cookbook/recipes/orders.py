import django_graphene_filters as orders

from . import models


class ObjectTypeOrder(orders.AdvancedOrderSet):
    class Meta:
        model = models.ObjectType
        fields = ["name", "description"]


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
        fields = ["name", "description"]


class AttributeOrder(orders.AdvancedOrderSet):
    object_type = orders.RelatedOrder(
        ObjectTypeOrder,
        field_name="object_type",
        queryset=models.ObjectType.objects.all(),
    )

    class Meta:
        model = models.Attribute
        fields = ["name", "description"]


class ValueOrder(orders.AdvancedOrderSet):
    attribute = orders.RelatedOrder(
        AttributeOrder,
        field_name="attribute",
        queryset=models.Attribute.objects.all(),
    )

    class Meta:
        model = models.Value
        fields = ["value", "description"]
