"""Tests for M2M-like aggregate traversal via live GraphQL queries.

The cookbook's Value model acts as a manual M2M through table between
Object and Attribute.  These tests verify that nested aggregates work
correctly when traversing this join in both directions:

1. Attribute -> values -> aggregates (per-Attribute Value stats)
2. Object -> values -> aggregates (per-Object Value stats, already
   covered in test_aggregates_edge_aggregates.py)

This exercises the same code paths as a real M2M would, since the
nested connection's queryset is scoped to the parent node.
"""

import json
from collections import Counter

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import seed_data
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()

COUNT = 5

# Attribute -> values -> aggregates: per-Attribute stats on Values
ATTR_TO_VALUES_QUERY = """
    query AttrToValues {
      allAttributes(filter: { objectType: { description: { icontains: "geo" } } }) {
        edges {
          node {
            name
            values {
              aggregates {
                count
                value {
                  count
                  min
                  max
                  uniques { value count }
                }
              }
            }
          }
        }
        aggregates {
          count
          name {
            count
            min
            max
            uniques { value count }
          }
        }
      }
    }
"""

# Object -> values -> aggregates: per-Object stats on Values
# (reverse direction through the same Value join table)
OBJ_TO_VALUES_QUERY = """
    query ObjToValues {
      allObjects(filter: { objectType: { description: { icontains: "geo" } } }) {
        edges {
          node {
            name
            values {
              aggregates {
                count
                value {
                  count
                  min
                  max
                }
              }
            }
          }
        }
        aggregates {
          count
        }
      }
    }
"""


class M2MLikeAggregateTests(GraphQLTestCase):
    """Test aggregates traversing the Value join table in both directions."""

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        self.staff = User.objects.create_user(username="staff_m2m", password="testpass", is_staff=True)
        self.client.login(username="staff_m2m", password="testpass")

        self.geo_ot = ObjectType.objects.get(name="geo")

    def test_attribute_to_values_edge_aggregates(self):
        """Each Attribute's nested values.aggregates is scoped to that Attribute."""
        response = self.query(ATTR_TO_VALUES_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allAttributes"]["edges"]

        self.assertGreater(len(edges), 0)

        for edge in edges:
            attr_name = edge["node"]["name"]
            values_agg = edge["node"]["values"]["aggregates"]

            # Get the Attribute from DB
            attr = Attribute.objects.get(name=attr_name, object_type=self.geo_ot)

            # Expected: all Values for this Attribute (staff sees all)
            expected_values = Value.objects.filter(attribute=attr)
            expected_count = expected_values.count()

            self.assertEqual(
                values_agg["count"],
                expected_count,
                f"Attribute '{attr_name}': count expected {expected_count}, got {values_agg['count']}",
            )

            if expected_count > 0:
                val_list = sorted(expected_values.values_list("value", flat=True))
                distinct_vals = sorted(set(val_list))

                self.assertEqual(values_agg["value"]["count"], len(distinct_vals))
                self.assertEqual(values_agg["value"]["min"], min(val_list))
                self.assertEqual(values_agg["value"]["max"], max(val_list))

                # Verify uniques
                expected_uniques = sorted(
                    [{"value": k, "count": v} for k, v in Counter(str(x) for x in val_list).items()],
                    key=lambda x: x["value"],
                )
                self.assertEqual(values_agg["value"]["uniques"], expected_uniques)

    def test_attribute_root_aggregates(self):
        """Root-level allAttributes aggregates count all geo Attributes."""
        response = self.query(ATTR_TO_VALUES_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        agg = content["data"]["allAttributes"]["aggregates"]

        # Staff sees all Attributes for geo ObjectType
        geo_attrs = Attribute.objects.filter(object_type=self.geo_ot)
        self.assertEqual(agg["count"], geo_attrs.count())

        attr_names = sorted(geo_attrs.values_list("name", flat=True))
        self.assertEqual(agg["name"]["min"], min(attr_names))
        self.assertEqual(agg["name"]["max"], max(attr_names))

    def test_object_to_values_edge_aggregates(self):
        """Each Object's nested values.aggregates is scoped to that Object."""
        response = self.query(OBJ_TO_VALUES_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]

        self.assertGreater(len(edges), 0)

        for edge in edges:
            obj_name = edge["node"]["name"]
            values_agg = edge["node"]["values"]["aggregates"]

            obj = Object.objects.get(name=obj_name)
            expected_values = Value.objects.filter(object=obj)
            expected_count = expected_values.count()

            self.assertEqual(
                values_agg["count"],
                expected_count,
                f"Object '{obj_name}': count expected {expected_count}, got {values_agg['count']}",
            )

            if expected_count > 0:
                val_list = sorted(expected_values.values_list("value", flat=True))
                distinct_vals = sorted(set(val_list))
                self.assertEqual(values_agg["value"]["count"], len(distinct_vals))
                self.assertEqual(values_agg["value"]["min"], min(val_list))
                self.assertEqual(values_agg["value"]["max"], max(val_list))

    def test_both_directions_consistent(self):
        """Total Values reachable from Objects and Attributes should be the same.

        Object -> values gives all Values for geo Objects.
        Attribute -> values gives all Values for geo Attributes.
        Both should sum to the same total (since all geo Values link to
        both a geo Object and a geo Attribute).
        """
        # Object direction
        response_obj = self.query(OBJ_TO_VALUES_QUERY)
        self.assertResponseNoErrors(response_obj)
        obj_edges = json.loads(response_obj.content)["data"]["allObjects"]["edges"]
        obj_total = sum(e["node"]["values"]["aggregates"]["count"] for e in obj_edges)

        # Attribute direction
        response_attr = self.query(ATTR_TO_VALUES_QUERY)
        self.assertResponseNoErrors(response_attr)
        attr_edges = json.loads(response_attr.content)["data"]["allAttributes"]["edges"]
        attr_total = sum(e["node"]["values"]["aggregates"]["count"] for e in attr_edges)

        # Both should equal the total number of Values for geo
        geo_obj_ids = Object.objects.filter(object_type=self.geo_ot).values_list("id", flat=True)
        total_values = Value.objects.filter(object_id__in=geo_obj_ids).count()

        self.assertEqual(obj_total, total_values, "Object-side sum doesn't match total Values")
        self.assertEqual(attr_total, total_values, "Attribute-side sum doesn't match total Values")
