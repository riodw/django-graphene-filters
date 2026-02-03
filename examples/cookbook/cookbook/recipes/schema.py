from graphene import Node
from graphene_django.types import DjangoObjectType

from graphene_django.filter import DjangoFilterConnectionField


import django_graphene_filters as filters
from django_graphene_filters import AdvancedDjangoFilterConnectionField

from . import models


"""
Filters
"""


class ObjectTypeFilter(filters.AdvancedFilterSet):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        filter_fields = {
            "name": "__all__",
            # "name": ["exact", "icontains"],
            "description": ["exact", "icontains"],
        }


class AttributeFilter(filters.AdvancedFilterSet):
    # Relationships
    # values = filters.RelatedFilter(
    #     "ValueFilter",
    #     field_name="values",
    #     queryset=models.Value.objects.all(),
    # )

    class Meta:
        model = models.Attribute
        interfaces = (Node,)
        filter_fields = {
            "name": ["exact", "icontains"],
            "description": ["exact", "icontains"],
        }


class ValueFilter(filters.AdvancedFilterSet):
    attribute = filters.RelatedFilter(
        AttributeFilter,
        field_name="attribute",
        queryset=models.Attribute.objects.all(),
    )

    class Meta:
        model = models.Value
        interfaces = (Node,)
        filter_fields = {
            "value": ["exact", "icontains"],
            "description": ["exact", "icontains"],
            # "object_type": ["exact"],
            # "object_type__name": ["exact"],
        }

class ObjectFilter(filters.AdvancedFilterSet):
    object_type = filters.RelatedFilter(
        ObjectTypeFilter,
        field_name="object_type",
        queryset=models.ObjectType.objects.all(),
    )
    # Relationships
    values = filters.RelatedFilter(
        ValueFilter,
        field_name="values",
        queryset=models.Value.objects.all(),
    )

    class Meta:
        model = models.Object
        interfaces = (Node,)
        filter_fields = {
            "name": ["exact", "icontains"],
            "description": ["exact", "icontains"],
            # "object_type": ["exact"],
            # "object_type__name": ["exact"],
        }


"""
Nodes
"""


class ObjectTypeNode(DjangoObjectType):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectTypeFilter
        # filter_fields = ["name"]

class AttributeNode(DjangoObjectType):
    class Meta:
        model = models.Attribute
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = AttributeFilter
        # filter_fields = ["name", "object_type"]


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


class ValueNode(DjangoObjectType):
    class Meta:
        model = models.Value
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ValueFilter
        # filter_fields = {
        #     "value": ["exact", "icontains"],
        #     "object": ["exact"],
        #     "attribute": ["exact"],
        # }


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
