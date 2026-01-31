from graphene import Node
from graphene_django.types import DjangoObjectType

from graphene_django.filter import DjangoFilterConnectionField


import django_graphene_filters as filters
from django_graphene_filters import AdvancedDjangoFilterConnectionField

from . import models


class ObjectTypeFilter(filters.AdvancedFilterSet):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        fields = {
            "name": ["exact", "icontains"],
            "description": ["exact", "icontains"],
        }

class ObjectFilter(filters.AdvancedFilterSet):
    object_type = filters.RelatedFilter(
        ObjectTypeFilter,
        field_name="object_type",
        queryset=models.ObjectType.objects.all(),
    )

    class Meta:
        model = models.Object
        interfaces = (Node,)
        fields = {
            "name": ["exact", "icontains"],
            "description": ["exact", "icontains"],
            # "object_type": ["exact"],
            # "object_type__name": ["exact"],
        }


class ObjectTypeNode(DjangoObjectType):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectTypeFilter
        # filter_fields = ["name"]


class ObjectNode(DjangoObjectType):
    class Meta:
        model = models.Object
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectFilter
        # filter_fields = {
        #     "name": ["exact", "icontains", "istartswith"],
        #     "object_type": ["exact"],
        #     "object_type__name": ["exact"],
        # }


class AttributeNode(DjangoObjectType):
    class Meta:
        model = models.Attribute
        interfaces = (Node,)
        fields = "__all__"
        filter_fields = ["name", "object_type"]


class ValueNode(DjangoObjectType):
    class Meta:
        model = models.Value
        interfaces = (Node,)
        fields = "__all__"
        filter_fields = {
            "value": ["exact", "icontains"],
            "object": ["exact"],
            "attribute": ["exact"],
        }


class Query:
    object_type = Node.Field(ObjectTypeNode)
    # all_object_types = DjangoFilterConnectionField(ObjectTypeNode)
    all_object_types = AdvancedDjangoFilterConnectionField(ObjectTypeNode)

    object = Node.Field(ObjectNode)
    # all_objects = DjangoFilterConnectionField(ObjectNode)
    all_objects = AdvancedDjangoFilterConnectionField(ObjectNode)

    attribute = Node.Field(AttributeNode)
    # all_attributes = DjangoFilterConnectionField(AttributeNode)
    all_attributes = AdvancedDjangoFilterConnectionField(AttributeNode)

    value = Node.Field(ValueNode)
    # all_values = DjangoFilterConnectionField(ValueNode)
    all_values = AdvancedDjangoFilterConnectionField(ValueNode)
