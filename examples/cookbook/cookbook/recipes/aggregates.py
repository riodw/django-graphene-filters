"""Aggregate class definitions for the cookbook example.

All aggregate classes override ``get_child_queryset`` to filter out
private rows (``is_private=True``) when traversing relationships.
This mirrors the ``get_queryset`` visibility logic in schema.py.
"""

import graphene
from graphql import GraphQLError

import django_graphene_filters as aggregates
from django_graphene_filters import RelatedAggregate

from . import models


def _private_aware_child_qs(self, rel_name, rel_agg):
    """Shared get_child_queryset that excludes is_private=True rows."""
    qs = super(type(self), self).get_child_queryset(rel_name, rel_agg)
    target_model = rel_agg.aggregate_class.Meta.model
    if hasattr(target_model, "is_private"):
        qs = qs.filter(is_private=False)
    return qs


class ObjectTypeAggregate(aggregates.AdvancedAggregateSet):
    # ObjectType → Object (Object.object_type FK)
    objects = RelatedAggregate("ObjectAggregate", field_name="object_type")
    # ObjectType → Attribute (Attribute.object_type FK)
    attributes = RelatedAggregate("AttributeAggregate", field_name="object_type")

    class Meta:
        model = models.ObjectType
        fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
            "description": ["count", "min", "max"],
        }

    get_child_queryset = _private_aware_child_qs


class AttributeAggregate(aggregates.AdvancedAggregateSet):
    object_type = RelatedAggregate("ObjectTypeAggregate", field_name="attributes")
    values = RelatedAggregate("ValueAggregate", field_name="attribute")

    class Meta:
        model = models.Attribute
        fields = {"name": ["count", "min", "max", "mode", "uniques"]}

    get_child_queryset = _private_aware_child_qs


class ObjectAggregate(aggregates.AdvancedAggregateSet):
    object_type = RelatedAggregate("ObjectTypeAggregate", field_name="objectss")
    values = RelatedAggregate("ValueAggregate", field_name="object")

    class Meta:
        model = models.Object
        fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
            "description": ["count", "min", "max"],
        }

    get_child_queryset = _private_aware_child_qs

    def check_name_uniques_permission(self, request):
        """Only staff can see unique name distribution."""
        user = getattr(request, "user", None)
        if not user or not user.is_staff:
            raise GraphQLError("You must be a staff user to view name uniques.")


class ValueAggregate(aggregates.AdvancedAggregateSet):
    """Aggregate for Value model with a custom geographic centroid stat."""

    attribute = RelatedAggregate(AttributeAggregate, field_name="values")
    object_ref = RelatedAggregate(ObjectAggregate, field_name="values")

    class Meta:
        model = models.Value
        fields = {
            "value": ["count", "min", "max", "mode", "uniques", "centroid"],
        }
        custom_stats = {
            "centroid": graphene.String,
        }

    get_child_queryset = _private_aware_child_qs

    def compute_value_centroid(self, queryset):
        """Compute the geographic centroid from latitude/longitude Values.

        Filters the queryset to only latitude and longitude attributes,
        parses the text values to floats, and returns the mean as "lat, lng".

        Returns None if no geo data is present in the queryset.
        """
        geo_values = queryset.filter(
            attribute__name__in=["latitude", "longitude"],
        ).values_list("attribute__name", "value")

        latitudes = []
        longitudes = []
        for attr_name, val in geo_values:
            try:
                num = float(val)
            except (ValueError, TypeError):
                continue
            if attr_name == "latitude":
                latitudes.append(num)
            else:
                longitudes.append(num)

        if not latitudes or not longitudes:
            return None

        mean_lat = round(sum(latitudes) / len(latitudes), 6)
        mean_lng = round(sum(longitudes) / len(longitudes), 6)
        return f"{mean_lat}, {mean_lng}"
