from graphene import Node

from django_graphene_filters import (
    AdvancedDjangoFilterConnectionField,
    AdvancedDjangoObjectType,
    apply_cascade_permissions,
)

from . import models
from .filters import (
    AttributeFilter,
    ObjectFilter,
    ObjectTypeFilter,
    ValueFilter,
)
from .orders import (
    AttributeOrder,
    ObjectOrder,
    ObjectTypeOrder,
    ValueOrder,
)

"""
Nodes
"""


class ObjectTypeNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectTypeFilter
        orderset_class = ObjectTypeOrder
        search_fields = (
            "name",
            "description",
        )

    @classmethod
    def get_queryset(cls, queryset, info):
        """Staff or users with view_objecttype permission see everything; others see public only."""
        user = getattr(info.context, "user", None)
        if user and (user.is_staff or user.has_perm("recipes.view_objecttype")):
            return queryset
        return queryset.filter(is_private=False)


class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Object
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ObjectFilter
        orderset_class = ObjectOrder
        search_fields = (
            "name",
            "description",
            "object_type__name",
            "object_type__description",
        )

    @classmethod
    def get_queryset(cls, queryset, info):
        """Staff or users with view_object permission see everything; others see public only."""
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return queryset
        elif user and user.has_perm("recipes.view_object"):
            return queryset.filter(is_private=False)
        return apply_cascade_permissions(cls, queryset.filter(is_private=False), info)


class AttributeNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Attribute
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = AttributeFilter
        orderset_class = AttributeOrder
        search_fields = (
            "name",
            "description",
            "object_type__name",
            "object_type__description",
        )

    @classmethod
    def get_queryset(cls, queryset, info):
        """Staff or users with view_attribute permission see everything; others see public only."""
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return queryset
        elif user and user.has_perm("recipes.view_attribute"):
            return queryset.filter(is_private=False)
        return apply_cascade_permissions(cls, queryset.filter(is_private=False), info)


class ValueNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Value
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = ValueFilter
        orderset_class = ValueOrder
        search_fields = (
            "value",
            "description",
            "attribute__name",
            "object__name",
        )

    @classmethod
    def get_queryset(cls, queryset, info):
        """Staff or users with view_value permission see everything; others see public only."""
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return queryset
        elif user and user.has_perm("recipes.view_value"):
            return queryset.filter(is_private=False)
        return apply_cascade_permissions(cls, queryset.filter(is_private=False), info)


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
