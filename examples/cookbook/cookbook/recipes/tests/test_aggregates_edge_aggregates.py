"""Tests for nested connection aggregates (aggregates inside edges).

Validates that ``allObjects { edges { node { values { aggregates { ... } } } } }``
returns per-Object Value aggregates scoped correctly for three user types:
1. Staff — sees ALL values (including is_private=True)
2. Unauthenticated — sees only public values (via get_queryset cascade)
3. Regular user (no perms) — same as unauthenticated

Each test verifies:
- The aggregate query succeeds without errors
- Aggregate counts differ between staff and non-staff (due to is_private filtering)
- Stat values (count, min, max) match independently computed expected values
"""

import json
import warnings
from collections import Counter

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import seed_data
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()

COUNT = 5

EDGE_AGGREGATES_QUERY = """
    query EdgeAggregates {
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
                  mode
                  uniques { value count }
                }
              }
            }
          }
        }
      }
    }
"""


class EdgeAggregateTests(GraphQLTestCase):
    """Test aggregates on nested connections inside edges."""

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        # Suppress InputObjectType overwrite warnings caused by test-ordering
        # interactions with the global graphene type registry.
        warnings.filterwarnings("ignore", message="InputObjectType.*was previously built")
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        self.geo_ot = ObjectType.objects.get(name="geo")

        # Create users
        self.staff_user = User.objects.create_user(username="staff_edge", password="testpass", is_staff=True)
        self.regular_user = User.objects.create_user(
            username="regular_edge", password="testpass", is_staff=False
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _run_query(self):
        """Execute the edge aggregates query and return parsed edges."""
        response = self.query(EDGE_AGGREGATES_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        return content["data"]["allObjects"]["edges"]

    def _validate_edge_aggregates(self, edges, value_qs_fn, label):
        """Validate edge aggregates against a queryset function.

        Args:
            edges: The GraphQL response edges list.
            value_qs_fn: A callable(obj) -> QuerySet that returns the expected
                         Values for a given Object, scoped to the user's visibility.
            label: Label for assertion messages.
        """
        if len(edges) == 0:
            # No visible Objects for this user (all may be is_private=True).
            # This is valid — nothing to validate.
            return

        for edge in edges:
            node = edge["node"]
            obj_name = node["name"]
            values_agg = node["values"]["aggregates"]

            obj = Object.objects.get(name=obj_name)
            expected_qs = value_qs_fn(obj)
            expected_count = expected_qs.count()

            # Count
            self.assertEqual(
                values_agg["count"],
                expected_count,
                f"[{label}] Object '{obj_name}': count expected {expected_count}, got {values_agg['count']}",
            )

            if expected_count > 0:
                val_list = sorted(expected_qs.values_list("value", flat=True))
                distinct_vals = sorted(set(val_list))

                # value.count (distinct)
                self.assertEqual(
                    values_agg["value"]["count"],
                    len(distinct_vals),
                    f"[{label}] Object '{obj_name}': value.count expected {len(distinct_vals)}, "
                    f"got {values_agg['value']['count']}",
                )

                # value.min
                self.assertEqual(
                    values_agg["value"]["min"],
                    min(val_list),
                    f"[{label}] Object '{obj_name}': value.min mismatch",
                )

                # value.max
                self.assertEqual(
                    values_agg["value"]["max"],
                    max(val_list),
                    f"[{label}] Object '{obj_name}': value.max mismatch",
                )

                # uniques
                expected_uniques = sorted(
                    [{"value": k, "count": v} for k, v in Counter(str(x) for x in val_list).items()],
                    key=lambda x: x["value"],
                )
                self.assertEqual(
                    values_agg["value"]["uniques"],
                    expected_uniques,
                    f"[{label}] Object '{obj_name}': uniques mismatch",
                )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_staff_edge_aggregates(self):
        """Staff sees ALL values per Object (no is_private filtering)."""
        self.client.login(username="staff_edge", password="testpass")
        edges = self._run_query()

        self._validate_edge_aggregates(
            edges,
            lambda obj: Value.objects.filter(object=obj),
            "staff",
        )

    def _cascade_visible_values(self, obj):
        """Return Values visible under cascade permissions (non-staff).

        get_queryset for ValueNode applies cascade: is_private=False AND
        the Value's Attribute must also be visible (is_private=False with
        a public ObjectType).
        """
        public_ot_ids = ObjectType.objects.filter(is_private=False).values_list("id", flat=True)
        visible_attr_ids = Attribute.objects.filter(
            is_private=False, object_type_id__in=public_ot_ids
        ).values_list("id", flat=True)
        return Value.objects.filter(
            object=obj,
            is_private=False,
            attribute_id__in=visible_attr_ids,
        )

    def test_unauthenticated_edge_aggregates(self):
        """Unauthenticated user sees only cascade-visible values per Object."""
        self.client.logout()
        edges = self._run_query()

        self._validate_edge_aggregates(
            edges,
            self._cascade_visible_values,
            "unauthenticated",
        )

    def test_regular_user_edge_aggregates(self):
        """Regular user (no perms) sees only cascade-visible values."""
        self.client.login(username="regular_edge", password="testpass")
        edges = self._run_query()

        self._validate_edge_aggregates(
            edges,
            self._cascade_visible_values,
            "regular",
        )

    def test_staff_sees_more_than_regular(self):
        """Staff aggregates should include private values that regular users don't see.

        At least one Object should have different aggregate counts between
        staff and regular users (since is_private is random on Values with
        a ~50/50 split across 5 objects × 3 attributes = 15 values).
        """
        # Staff query
        self.client.login(username="staff_edge", password="testpass")
        staff_edges = self._run_query()

        # Regular query
        self.client.login(username="regular_edge", password="testpass")
        regular_edges = self._run_query()

        staff_counts = {e["node"]["name"]: e["node"]["values"]["aggregates"]["count"] for e in staff_edges}
        regular_counts = {
            e["node"]["name"]: e["node"]["values"]["aggregates"]["count"] for e in regular_edges
        }

        # Staff should see >= regular for every Object
        for name in staff_counts:
            if name in regular_counts:
                self.assertGreaterEqual(
                    staff_counts[name],
                    regular_counts[name],
                    f"Object '{name}': staff count ({staff_counts[name]}) < regular count "
                    f"({regular_counts[name]})",
                )

        # At least one Object should have a difference (probabilistic but very likely
        # with 15 values and ~50% private)
        any_different = any(staff_counts.get(name, 0) != regular_counts.get(name, 0) for name in staff_counts)
        self.assertTrue(
            any_different,
            "Expected at least one Object where staff sees more values than regular user. "
            f"Staff: {staff_counts}, Regular: {regular_counts}",
        )
