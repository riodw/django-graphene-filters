from graphene import Node

from django_graphene_filters import (
    AdvancedDjangoFilterConnectionField,
    AdvancedDjangoObjectType,
    apply_cascade_permissions,
)

from . import aggregates
from . import fields as fieldsets
from . import filters
from . import models
from . import orders

"""
Nodes
"""


class ObjectTypeNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = filters.ObjectTypeFilter
        orderset_class = orders.ObjectTypeOrder
        aggregate_class = aggregates.ObjectTypeAggregate
        fields_class = fieldsets.ObjectTypeFieldSet
        search_fields = (
            "name",
            "description",
        )

    @classmethod
    def get_queryset(cls, queryset, info):
        """Staff or users with view_objecttype permission see everything; others see public only."""
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return queryset
        elif user and user.has_perm("recipes.view_objecttype"):
            return queryset.filter(is_private=False)
        return apply_cascade_permissions(cls, queryset.filter(is_private=False), info)


class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        model = models.Object
        interfaces = (Node,)
        fields = "__all__"
        filterset_class = filters.ObjectFilter
        orderset_class = orders.ObjectOrder
        aggregate_class = aggregates.ObjectAggregate
        fields_class = fieldsets.ObjectFieldSet
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
        filterset_class = filters.AttributeFilter
        orderset_class = orders.AttributeOrder
        aggregate_class = aggregates.AttributeAggregate
        fields_class = fieldsets.AttributeFieldSet
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
        fields = [
            "id",
            "value",
            # description - not included for permissions testing
            "attribute",
            "object",
            "is_private",
            "created_date",
            "updated_date",
        ]
        filterset_class = filters.ValueFilter
        orderset_class = orders.ValueOrder
        aggregate_class = aggregates.ValueAggregate
        fields_class = fieldsets.ValueFieldSet
        search_fields = (
            "value",
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
