from graphene import Node

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


class ObjectFilter(filters.AdvancedFilterSet):
    object_type = filters.RelatedFilter(
        ObjectTypeFilter,
        field_name="object_type",
        queryset=models.ObjectType.objects.all(),
    )
    # Relationships
    values = filters.RelatedFilter(
        "ValueFilter",
        field_name="values",
        queryset=models.Value.objects.all(),
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


class AttributeFilter(filters.AdvancedFilterSet):
    object_type = filters.RelatedFilter(
        ObjectTypeFilter,
        field_name="object_type",
        queryset=models.ObjectType.objects.all(),
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
            "attribute__name": ["exact"],
            "attribute__object_type__name": ["exact"],
        }
