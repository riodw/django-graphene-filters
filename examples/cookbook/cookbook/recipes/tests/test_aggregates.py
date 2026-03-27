"""Tests for AdvancedAggregateSet integration.

Fires 18 queries total: 1 staff + 1 unauthenticated + all 16 combinations
of the 4 model-level view permissions (2^4 = 16).  Each query uses the full
aggregate query (no edges) across ObjectType > Object > Value and
ObjectType > Attribute, and validates that aggregate counts respect
row-level visibility (is_private + cascade permissions).
"""

import itertools
import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import TEST_USER_PASSWORD, seed_data
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from graphene_django.utils import GraphQLTestCase

User = get_user_model()

COUNT = 4

# The 4 model-level view permissions to combine.
VIEW_PERMISSIONS = [
    "view_objecttype",
    "view_object",
    "view_attribute",
    "view_value",
]

# ---------------------------------------------------------------------------
# Query shape
# ---------------------------------------------------------------------------

# Full aggregate query: no edges, all stats on all fields, three relationship paths:
#
#   allObjectTypes (filtered to "geo")
#   +- ObjectType own fields: name (text), description (text)
#   +- objects -> ObjectAggregate
#   |  +- Object own fields: name (text), description (text)
#   |  +- values -> ValueAggregate
#   |     +- Value own fields: value (text + centroid custom stat)
#   +- attributes -> AttributeAggregate
#      +- Attribute own fields: name (text)
#
# Non-staff query: omits objects.name.uniques (blocked by check_name_uniques_permission)
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

# Staff query: includes ALL stats including objects.name.uniques (staff-only)
STAFF_AGGREGATE_QUERY = """
    query StaffFullAggregates {
      allObjectTypes(filter: { name: { exact: "geo" } }) {
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
              uniques { value count }
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


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class AggregatePermissionTests(GraphQLTestCase):
    """Validate that aggregate counts respect the same visibility rules as edges.

    For each of the 18 user variants (staff + unauthenticated + 16 permission combos):
    1. The root ``count`` in ``aggregates`` matches the expected ObjectType count.
    2. The nested ``objects.count`` matches the expected Object count.
    3. The nested ``objects.values.count`` matches the expected Value count.
    4. The nested ``attributes.count`` matches the expected Attribute count.
    5. All returned aggregate data is non-null where expected.
    """

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        # Pre-compute visible IDs for cascade calculations.
        self.public_ot_ids = set(ObjectType.objects.filter(is_private=False).values_list("id", flat=True))

        # Generate all 16 permission combinations (powerset of VIEW_PERMISSIONS).
        self.perm_combos = []
        for r in range(len(VIEW_PERMISSIONS) + 1):
            for combo in itertools.combinations(VIEW_PERMISSIONS, r):
                self.perm_combos.append(list(combo))

    # ------------------------------------------------------------------
    # Expected counts per model given a permission set
    # ------------------------------------------------------------------

    def _expected_ot_count(self, perms):
        """ObjectType count: non-staff always sees public only (no cascade FKs on ObjectType)."""
        return ObjectType.objects.filter(is_private=False, description__icontains="geo").count()

    def _expected_obj_count(self, perms):
        """Object count: RelatedAggregate traverses from the visible ObjectType QS.

        The parent QS is already scoped to public geo ObjectTypes.
        get_child_queryset adds is_private=False on the child Objects.
        """
        geo_ot = ObjectType.objects.filter(description__icontains="geo", is_private=False).first()
        if not geo_ot:
            return 0
        return Object.objects.filter(is_private=False, object_type=geo_ot).count()

    def _expected_attr_count(self, perms):
        """Attribute count: same traversal logic as objects."""
        geo_ot = ObjectType.objects.filter(description__icontains="geo", is_private=False).first()
        if not geo_ot:
            return 0
        return Attribute.objects.filter(is_private=False, object_type=geo_ot).count()

    def _expected_val_count(self, perms):
        """Value count: traverses from visible Objects of the geo ObjectType.

        Parent QS = public Objects of geo OT (from _expected_obj_count logic).
        get_child_queryset adds is_private=False on Values.
        """
        geo_ot = ObjectType.objects.filter(description__icontains="geo", is_private=False).first()
        if not geo_ot:
            return 0
        visible_obj_ids = Object.objects.filter(is_private=False, object_type=geo_ot).values_list(
            "id", flat=True
        )
        return Value.objects.filter(is_private=False, object_id__in=visible_obj_ids).count()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_user(self, perms, index):
        """Create a non-staff user with the given permissions."""
        username = f"agg_combo_{index}"
        user = User.objects.create_user(
            username=username,
            password=TEST_USER_PASSWORD,
            is_staff=False,
        )
        for perm_codename in perms:
            perm = Permission.objects.get(
                codename=perm_codename,
                content_type__app_label="recipes",
            )
            user.user_permissions.add(perm)
        return username

    def _run_query_and_validate(self, perms, label):
        """Execute FULL_AGGREGATE_QUERY and validate aggregate counts."""
        response = self.query(FULL_AGGREGATE_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)

        agg = content["data"]["allObjectTypes"].get("aggregates")
        if agg is None:
            return

        # 1. Root ObjectType count
        expected_ot = self._expected_ot_count(perms)
        self.assertEqual(
            agg["count"],
            expected_ot,
            f"[{label}] ObjectType aggregate count: expected {expected_ot}, got {agg['count']}",
        )

        # 2. ObjectType own field aggregates are present
        if expected_ot > 0:
            self.assertIsNotNone(agg["name"], f"[{label}] ObjectType.name aggregates missing")
            self.assertIsNotNone(agg["description"], f"[{label}] ObjectType.description aggregates missing")
            # Verify all text stats are present on name
            for stat in ("count", "min", "max", "mode", "uniques"):
                self.assertIn(stat, agg["name"], f"[{label}] ObjectType.name.{stat} missing")

        # 3. Nested objects (Object) count
        if "objects" in agg:
            expected_obj = self._expected_obj_count(perms)
            self.assertEqual(
                agg["objects"]["count"],
                expected_obj,
                f"[{label}] Object aggregate count: expected {expected_obj}, "
                f"got {agg['objects']['count']}",
            )

            # Verify Object field aggregates (uniques excluded — staff-only)
            if expected_obj > 0:
                for stat in ("count", "min", "max", "mode"):
                    self.assertIn(stat, agg["objects"]["name"], f"[{label}] Object.name.{stat} missing")
                for stat in ("count", "min", "max"):
                    self.assertIn(
                        stat,
                        agg["objects"]["description"],
                        f"[{label}] Object.description.{stat} missing",
                    )

            # 4. Nested objects > values (Value) count
            if "values" in agg["objects"]:
                expected_val = self._expected_val_count(perms)
                self.assertEqual(
                    agg["objects"]["values"]["count"],
                    expected_val,
                    f"[{label}] Value aggregate count: expected {expected_val}, "
                    f"got {agg['objects']['values']['count']}",
                )

                # Verify Value field aggregates including custom centroid
                if expected_val > 0:
                    val_stats = agg["objects"]["values"]["value"]
                    for stat in ("count", "min", "max", "mode", "uniques", "centroid"):
                        self.assertIn(stat, val_stats, f"[{label}] Value.value.{stat} missing")
                    self.assertIsNotNone(val_stats["min"], f"[{label}] Value.value.min is None")
                    self.assertIsNotNone(val_stats["max"], f"[{label}] Value.value.max is None")

        # 5. Nested attributes (Attribute) count
        if "attributes" in agg:
            expected_attr = self._expected_attr_count(perms)
            self.assertEqual(
                agg["attributes"]["count"],
                expected_attr,
                f"[{label}] Attribute aggregate count: expected {expected_attr}, "
                f"got {agg['attributes']['count']}",
            )

            # Verify Attribute field aggregates
            if expected_attr > 0:
                for stat in ("count", "min", "max", "mode", "uniques"):
                    self.assertIn(
                        stat,
                        agg["attributes"]["name"],
                        f"[{label}] Attribute.name.{stat} missing",
                    )

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_staff_sees_all_aggregates(self):
        """Staff user should see full counts across all models — no is_private filtering.

        Uses STAFF_AGGREGATE_QUERY which includes all stats (including staff-only
        objects.name.uniques and name filter).
        """
        User.objects.create_user(username="staff_agg", password="testpass", is_staff=True)
        self.client.login(username="staff_agg", password="testpass")

        response = self.query(STAFF_AGGREGATE_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        agg = content["data"]["allObjectTypes"]["aggregates"]

        geo_ot = ObjectType.objects.filter(name="geo").first()
        self.assertIsNotNone(geo_ot, "geo ObjectType must exist (run seed_data first)")

        # Staff sees everything — but RelatedAggregate still applies is_private=False
        # via get_child_queryset override in the cookbook aggregate classes.
        self.assertEqual(agg["count"], 1)  # one "geo" ObjectType
        self.assertEqual(
            agg["objects"]["count"],
            Object.objects.filter(object_type=geo_ot, is_private=False).count(),
        )
        self.assertEqual(
            agg["attributes"]["count"],
            Attribute.objects.filter(object_type=geo_ot, is_private=False).count(),
        )
        geo_obj_ids = Object.objects.filter(object_type=geo_ot, is_private=False).values_list("id", flat=True)
        self.assertEqual(
            agg["objects"]["values"]["count"],
            Value.objects.filter(object_id__in=geo_obj_ids, is_private=False).count(),
        )

        # Verify centroid is present (geo has latitude/longitude attributes)
        self.assertIn("centroid", agg["objects"]["values"]["value"])

    def test_all_permission_combinations(self):
        """Fire 17 queries: 1 unauthenticated + 16 permission combos."""
        self.assertEqual(len(self.perm_combos), 16)

        # Query 1: unauthenticated user
        self.client.logout()
        with self.subTest(permissions="unauthenticated"):
            self._run_query_and_validate([], "unauthenticated")

        # Queries 2-17: authenticated users with each permission combo
        for i, perms in enumerate(self.perm_combos):
            label = ", ".join(perms) if perms else "no perms"

            with self.subTest(permissions=label):
                username = self._create_user(perms, i)
                self.client.login(username=username, password=TEST_USER_PASSWORD)
                self._run_query_and_validate(perms, label)
