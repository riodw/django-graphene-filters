from graphene import Node
from graphql import GraphQLError

import django_graphene_filters as filters

from . import models


class ObjectTypeFilter(filters.AdvancedFilterSet):
    class Meta:
        model = models.ObjectType
        interfaces = (Node,)
        filter_fields = {
            "name": "__all__",
            # "name": ["exact", "icontains"],
            "description": ["exact", "icontains"],
        }

    def check_name_permission(self, request):
        """Only staff users may filter by ObjectType.name."""
        user = getattr(request, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("You must be a staff user to filter by ObjectType name.")


class ObjectFilter(filters.AdvancedFilterSet):
    object_type = filters.RelatedFilter(
        ObjectTypeFilter,
        field_name="object_type",
    )
    # Relationships
    values = filters.RelatedFilter(
        "ValueFilter",
        field_name="values",
    )

    class Meta:
        model = models.Object
        interfaces = (Node,)
        filter_fields = {
            "name": "__all__",
            "description": ["exact", "icontains"],
            # "object_type": ["exact"],
            "object_type__name": ["exact"],
        }

    # TODO: Implement permission check?
    # def check_values_permission(self, queryset, request):
    #     """Only staff users may filter by Object.values."""
    #     user = getattr(request, "user", None)
    #     if not user or not user.is_staff:
    #         return queryset.filter(object_type__name="Secret")
    #     return queryset
            


class AttributeFilter(filters.AdvancedFilterSet):
    object_type = filters.RelatedFilter(
        ObjectTypeFilter,
        field_name="object_type",
    )
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
    # Explicit queryset: excludes attributes named "Secret", acting as a scope
    # boundary. Values linked to a "Secret" attribute will never appear in results.
    attribute = filters.RelatedFilter(
        AttributeFilter,
        field_name="attribute",
        queryset=models.Attribute.objects.exclude(name="Secret"),
    )

    class Meta:
        model = models.Value
        interfaces = (Node,)
        filter_fields = {
            "value": ["exact", "icontains"],
            "description": ["exact", "icontains"],
            "attribute__name": ["exact"],
            "attribute__object_type__name": ["exact"],
        }
