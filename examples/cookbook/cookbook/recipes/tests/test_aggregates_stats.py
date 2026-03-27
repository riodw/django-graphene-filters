"""Tests that aggregate stat VALUES are correct (not just present).

Runs a single staff query against geo-seeded data and verifies every
returned stat against independently computed expected values from the DB.

Uses the same FULL_AGGREGATE_QUERY shape as test_aggregates_permissions.py.
"""

import json
import statistics
from collections import Counter

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import seed_data
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()

COUNT = 5

FULL_AGGREGATE_QUERY = """
    query FullAggregates {
      allObjectTypes(filter: { description: { icontains: "geo" } }) {
        aggregates {
          count

          name {
            count
            min
            max
            mode
            uniques { value count }
          }

          description {
            count
            min
            max
          }

          objects {
            count

            name {
              count
              min
              max
              mode
            }

            description {
              count
              min
              max
            }

            values {
              count

              value {
                count
                min
                max
                mode
                uniques { value count }
                centroid
              }
            }
          }

          attributes {
            count

            name {
              count
              min
              max
              mode
              uniques { value count }
            }
          }
        }
      }
    }
"""


def _compute_uniques(values):
    """Return sorted list of {value, count} dicts from a list of values."""
    counter = Counter(str(v) for v in values)
    return sorted([{"value": k, "count": v} for k, v in counter.items()], key=lambda x: x["value"])


def _mode_or_none(values):
    """Compute mode, return None if all values are unique or empty."""
    if not values:
        return None
    counter = Counter(values)
    max_count = max(counter.values())
    if max_count == 1:
        # All values are unique — no meaningful mode
        return None
    try:
        return statistics.mode(values)
    except statistics.StatisticsError:
        return None


class AggregateStatsTests(GraphQLTestCase):
    """Verify that aggregate stat values match independently computed expected values."""

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        # Login as staff to see everything and avoid permission checks
        self.staff = User.objects.create_user(username="staff_stats", password="testpass", is_staff=True)
        self.client.login(username="staff_stats", password="testpass")

        # Geo ObjectType (deterministically public)
        self.geo_ot = ObjectType.objects.get(name="geo")

        # The child querysets match what the aggregate system computes:
        # get_child_queryset filters is_private=False on children.
        self.geo_objects = Object.objects.filter(object_type=self.geo_ot, is_private=False)
        self.geo_attrs = Attribute.objects.filter(object_type=self.geo_ot, is_private=False)
        self.geo_values = Value.objects.filter(
            object__in=self.geo_objects,
            is_private=False,
        )

    def test_all_stat_values(self):
        """Single query: verify every stat value against the DB."""
        response = self.query(FULL_AGGREGATE_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        agg = content["data"]["allObjectTypes"]["aggregates"]

        # ---------------------------------------------------------------
        # Root: ObjectType aggregates (filtered to geo, 1 result)
        # ---------------------------------------------------------------
        self.assertEqual(agg["count"], 1)

        # ObjectType.name stats (only "geo" in the filtered set)
        ot_names = ["geo"]
        self.assertEqual(agg["name"]["count"], 1)
        self.assertEqual(agg["name"]["min"], "geo")
        self.assertEqual(agg["name"]["max"], "geo")
        self.assertEqual(agg["name"]["mode"], "geo")
        self.assertEqual(agg["name"]["uniques"], [{"value": "geo", "count": 1}])

        # ObjectType.description stats
        ot_descs = list(ObjectType.objects.filter(name="geo").values_list("description", flat=True))
        self.assertEqual(agg["description"]["count"], len(set(ot_descs)))
        self.assertEqual(agg["description"]["min"], min(ot_descs))
        self.assertEqual(agg["description"]["max"], max(ot_descs))

        # ---------------------------------------------------------------
        # objects: Object aggregates (public Objects of geo)
        # ---------------------------------------------------------------
        obj_agg = agg["objects"]
        expected_obj_count = self.geo_objects.count()
        self.assertEqual(obj_agg["count"], expected_obj_count)

        if expected_obj_count > 0:
            obj_names = sorted(self.geo_objects.values_list("name", flat=True))
            # name.count = distinct count
            distinct_names = sorted(set(obj_names))
            self.assertEqual(obj_agg["name"]["count"], len(distinct_names))
            self.assertEqual(obj_agg["name"]["min"], min(obj_names))
            self.assertEqual(obj_agg["name"]["max"], max(obj_names))

            expected_mode = _mode_or_none(obj_names)
            if expected_mode is not None:
                self.assertEqual(obj_agg["name"]["mode"], expected_mode)

            obj_descs = list(self.geo_objects.values_list("description", flat=True))
            distinct_descs = sorted(set(obj_descs))
            self.assertEqual(obj_agg["description"]["count"], len(distinct_descs))
            self.assertEqual(obj_agg["description"]["min"], min(obj_descs))
            self.assertEqual(obj_agg["description"]["max"], max(obj_descs))

        # ---------------------------------------------------------------
        # objects > values: Value aggregates (public Values of public geo Objects)
        # ---------------------------------------------------------------
        val_agg = obj_agg["values"]
        expected_val_count = self.geo_values.count()
        self.assertEqual(val_agg["count"], expected_val_count)

        if expected_val_count > 0:
            val_values = sorted(self.geo_values.values_list("value", flat=True))
            distinct_vals = sorted(set(val_values))

            self.assertEqual(val_agg["value"]["count"], len(distinct_vals))
            self.assertEqual(val_agg["value"]["min"], min(val_values))
            self.assertEqual(val_agg["value"]["max"], max(val_values))

            expected_mode = _mode_or_none(val_values)
            if expected_mode is not None:
                self.assertEqual(val_agg["value"]["mode"], expected_mode)

            # Verify uniques match
            expected_uniques = _compute_uniques(val_values)
            self.assertEqual(val_agg["value"]["uniques"], expected_uniques)

            # Verify centroid (computed from latitude + longitude values)
            lat_vals = list(
                self.geo_values.filter(attribute__name="latitude").values_list("value", flat=True)
            )
            lng_vals = list(
                self.geo_values.filter(attribute__name="longitude").values_list("value", flat=True)
            )
            if lat_vals and lng_vals:
                lats = [float(v) for v in lat_vals]
                lngs = [float(v) for v in lng_vals]
                expected_centroid = f"{round(sum(lats) / len(lats), 6)}, {round(sum(lngs) / len(lngs), 6)}"
                self.assertEqual(val_agg["value"]["centroid"], expected_centroid)
            else:
                # No geo data visible — centroid should be None
                self.assertIsNone(val_agg["value"]["centroid"])

        # ---------------------------------------------------------------
        # attributes: Attribute aggregates (public Attributes of geo)
        # ---------------------------------------------------------------
        attr_agg = agg["attributes"]
        expected_attr_count = self.geo_attrs.count()
        self.assertEqual(attr_agg["count"], expected_attr_count)

        if expected_attr_count > 0:
            attr_names = sorted(self.geo_attrs.values_list("name", flat=True))
            distinct_attr_names = sorted(set(attr_names))

            self.assertEqual(attr_agg["name"]["count"], len(distinct_attr_names))
            self.assertEqual(attr_agg["name"]["min"], min(attr_names))
            self.assertEqual(attr_agg["name"]["max"], max(attr_names))

            expected_mode = _mode_or_none(attr_names)
            if expected_mode is not None:
                self.assertEqual(attr_agg["name"]["mode"], expected_mode)

            expected_uniques = _compute_uniques(attr_names)
            self.assertEqual(attr_agg["name"]["uniques"], expected_uniques)
