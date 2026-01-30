from graphene import Node
from graphene_django.filter import DjangoFilterConnectionField
from graphene_django.types import DjangoObjectType

from cookbook.recipes.models import Attribute, Object, ObjectType, Value


class ObjectTypeNode(DjangoObjectType):
    class Meta:
        model = ObjectType
        interfaces = (Node,)
        fields = "__all__"
        filter_fields = ["name"]


class ObjectNode(DjangoObjectType):
    class Meta:
        model = Object
        interfaces = (Node,)
        fields = "__all__"
        filter_fields = {
            "name": ["exact", "icontains", "istartswith"],
            "object_type": ["exact"],
        }


class AttributeNode(DjangoObjectType):
    class Meta:
        model = Attribute
        interfaces = (Node,)
        fields = "__all__"
        filter_fields = ["name", "object_type"]


class ValueNode(DjangoObjectType):
    class Meta:
        model = Value
        interfaces = (Node,)
        fields = "__all__"
        filter_fields = {
            "value": ["exact", "icontains"],
            "object": ["exact"],
            "attribute": ["exact"],
        }


class Query:
    object_type = Node.Field(ObjectTypeNode)
    all_object_types = DjangoFilterConnectionField(ObjectTypeNode)

    object = Node.Field(ObjectNode)
    all_objects = DjangoFilterConnectionField(ObjectNode)

    attribute = Node.Field(AttributeNode)
    all_attributes = DjangoFilterConnectionField(AttributeNode)

    value = Node.Field(ValueNode)
    all_values = DjangoFilterConnectionField(ValueNode)
