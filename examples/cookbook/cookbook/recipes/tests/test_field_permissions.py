"""Field-level permission tests.

Fires 19 queries: 1 staff + 1 unauthenticated + 1 regular (no perms) +
all 16 combinations of the 4 model-level view permissions (2^4 = 16).

Each query uses the same deeply-nested shape and validates that
FieldSet-managed fields return the correct tiered content:

- description:   staff → real value, others → ""
- isPrivate:     staff → real value, others → False
- displayName:   authenticated → "{id} - {name}", anonymous → null
- createdDate:   staff → ISO, view_perm → YYYY-MM-DD, auth → YYYY-MM, anon → YYYY
- updatedDate:   staff → full, view_perm → day, auth → month, anon → epoch (gate denied)
"""

import itertools
import json
import re

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import TEST_USER_PASSWORD, seed_data
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from graphene_django.utils import GraphQLTestCase

User = get_user_model()

COUNT = 4

VIEW_PERMISSIONS = [
    "view_objecttype",
    "view_object",
    "view_attribute",
    "view_value",
]

# Regex patterns for date tier detection (all are ISO datetime strings from graphene DateTime)
# Staff: full precision    → 2026-03-27T15:30:45.123456+00:00
# view_perm: day precision → 2026-03-27T00:00:00+00:00
# auth: month precision    → 2026-03-01T00:00:00+00:00
# anon: year precision     → 2026-01-01T00:00:00+00:00
ISO_FULL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")  # any ISO datetime
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T00:00:00")  # time zeroed
MONTH_RE = re.compile(r"^\d{4}-\d{2}-01T00:00:00")  # day=01, time zeroed
YEAR_RE = re.compile(r"^\d{4}-01-01T00:00:00")  # month=01, day=01, time zeroed
EPOCH_RE = re.compile(r"^1970-01-01T00:00:00")  # gate denied → epoch default

# Query: exercises all FieldSet-managed fields across ObjectType → Object → Value.
# Value.description is excluded from schema (fields=[...] without description).
FIELD_PERM_QUERY = """
    query {
      allObjectTypes {
        edges {
          node {
            name
            description
            displayName
            createdDate
            updatedDate
            objectss {
              edges {
                node {
                  name
                  isPrivate
                  displayName
                  createdDate
                  updatedDate
                  values {
                    edges {
                      node {
                        value
                        displayName
                        createdDate
                        updatedDate
                      }
                    }
                  }
                }
              }
            }
          }
        }
      }
    }
"""


class FieldPermissionComboTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        self.perm_combos = []
        for r in range(len(VIEW_PERMISSIONS) + 1):
            for combo in itertools.combinations(VIEW_PERMISSIONS, r):
                self.perm_combos.append(list(combo))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_user(self, perms, index, staff=False):
        username = f"field_combo_{index}"
        user = User.objects.create_user(
            username=username,
            password=TEST_USER_PASSWORD,
            is_staff=staff,
        )
        for perm_codename in perms:
            perm = Permission.objects.get(
                codename=perm_codename,
                content_type__app_label="recipes",
            )
            user.user_permissions.add(perm)
        return username

    def _check_date(self, value, tier, label, path):
        """Assert a datetime string matches the expected tier precision."""
        if tier == "full":
            self.assertRegex(value, ISO_FULL_RE, f"[{label}] {path} expected full ISO, got '{value}'")
        elif tier == "day":
            self.assertRegex(value, DAY_RE, f"[{label}] {path} expected day precision, got '{value}'")
        elif tier == "month":
            self.assertRegex(value, MONTH_RE, f"[{label}] {path} expected month precision, got '{value}'")
        elif tier == "year":
            self.assertRegex(value, YEAR_RE, f"[{label}] {path} expected year precision, got '{value}'")
        elif tier == "epoch":
            self.assertRegex(value, EPOCH_RE, f"[{label}] {path} expected epoch, got '{value}'")
        elif tier == "null":
            self.assertIsNone(value, f"[{label}] {path} expected null, got '{value}'")

    def _date_tier(self, is_staff, has_perm):
        """Return the expected date tier for a given role."""
        if is_staff:
            return "full"
        if has_perm:
            return "day"
        return "month"

    def _validate_response(self, content, perms, label, is_staff, is_authenticated):
        edges = content["data"]["allObjectTypes"]["edges"]
        has_view_ot = "view_objecttype" in perms
        has_view_obj = "view_object" in perms
        has_view_val = "view_value" in perms

        for ot_edge in edges:
            ot = ot_edge["node"]

            # description: staff → real, others → ""
            if is_staff:
                # Staff sees real description (seeded data has non-empty descriptions)
                self.assertTrue(
                    len(ot["description"]) > 0, f"[{label}] OT description should be real for staff"
                )
            else:
                self.assertEqual(
                    ot["description"], "", f"[{label}] OT description should be '' for non-staff"
                )

            # displayName: authenticated → "{id} - {name}", anon → null
            if is_authenticated:
                self.assertIsNotNone(ot["displayName"], f"[{label}] OT displayName should exist for auth")
                self.assertIn(" - ", ot["displayName"])
            else:
                self.assertIsNone(ot["displayName"], f"[{label}] OT displayName should be null for anon")

            # createdDate: tiered (anon gets year precision)
            if is_staff:
                self._check_date(ot["createdDate"], "full", label, "OT.createdDate")
            elif has_view_ot:
                self._check_date(ot["createdDate"], "day", label, "OT.createdDate")
            elif is_authenticated:
                self._check_date(ot["createdDate"], "month", label, "OT.createdDate")
            else:
                self._check_date(ot["createdDate"], "year", label, "OT.createdDate")

            # updatedDate: gate blocks anonymous → epoch; rest tiered via resolve_
            if not is_authenticated:
                self._check_date(ot["updatedDate"], "epoch", label, "OT.updatedDate")
            else:
                tier = self._date_tier(is_staff, has_view_ot)
                self._check_date(ot["updatedDate"], tier, label, "OT.updatedDate")

            # Objects
            for obj_edge in ot["objectss"]["edges"]:
                obj = obj_edge["node"]

                # isPrivate: staff → real, others → False
                if not is_staff:
                    self.assertFalse(
                        obj["isPrivate"], f"[{label}] Obj isPrivate should be False for non-staff"
                    )

                # displayName
                if is_authenticated:
                    self.assertIsNotNone(
                        obj["displayName"], f"[{label}] Obj displayName should exist for auth"
                    )
                else:
                    self.assertIsNone(
                        obj["displayName"], f"[{label}] Obj displayName should be null for anon"
                    )

                # createdDate
                if is_staff:
                    self._check_date(obj["createdDate"], "full", label, "Obj.createdDate")
                elif has_view_obj:
                    self._check_date(obj["createdDate"], "day", label, "Obj.createdDate")
                elif is_authenticated:
                    self._check_date(obj["createdDate"], "month", label, "Obj.createdDate")
                else:
                    self._check_date(obj["createdDate"], "year", label, "Obj.createdDate")

                # updatedDate
                if not is_authenticated:
                    self._check_date(obj["updatedDate"], "epoch", label, "Obj.updatedDate")
                else:
                    tier = self._date_tier(is_staff, has_view_obj)
                    self._check_date(obj["updatedDate"], tier, label, "Obj.updatedDate")

                # Values
                for val_edge in obj["values"]["edges"]:
                    val = val_edge["node"]

                    # ValueFieldSet.resolve_updated_date raises for anonymous,
                    # which nulls the entire non-nullable node in partial errors.
                    if val is None:
                        continue

                    if is_authenticated:
                        self.assertIsNotNone(
                            val["displayName"], f"[{label}] Val displayName should exist for auth"
                        )
                    else:
                        self.assertIsNone(val["displayName"], f"[{label}] Val displayName should be null")

                    if is_staff:
                        self._check_date(val["createdDate"], "full", label, "Val.createdDate")
                    elif has_view_val:
                        self._check_date(val["createdDate"], "day", label, "Val.createdDate")
                    elif is_authenticated:
                        self._check_date(val["createdDate"], "month", label, "Val.createdDate")
                    else:
                        self._check_date(val["createdDate"], "year", label, "Val.createdDate")

                    if not is_authenticated:
                        self._check_date(val["updatedDate"], "epoch", label, "Val.updatedDate")
                    else:
                        tier = self._date_tier(is_staff, has_view_val)
                        self._check_date(val["updatedDate"], tier, label, "Val.updatedDate")

    # ------------------------------------------------------------------
    # Test
    # ------------------------------------------------------------------

    def test_all_permission_combinations(self):
        """Fire 19 queries: staff + unauthenticated + regular + 16 permission combos."""
        self.assertEqual(len(self.perm_combos), 16)

        # Query 1: staff
        username = self._create_user([], 99, staff=True)
        self.client.login(username=username, password=TEST_USER_PASSWORD)
        with self.subTest(permissions="staff"):
            response = self.query(FIELD_PERM_QUERY)
            self.assertResponseNoErrors(response)
            content = json.loads(response.content)
            self._validate_response(content, VIEW_PERMISSIONS, "staff", is_staff=True, is_authenticated=True)

        # Query 2: unauthenticated
        # Note: ValueFieldSet.resolve_updated_date raises GraphQLError for
        # anonymous users (demonstrates resolve_ handling its own denial).
        # This produces partial errors in the response — data is still present
        # with epoch defaults, but errors array is non-empty.
        self.client.logout()
        with self.subTest(permissions="unauthenticated"):
            response = self.query(FIELD_PERM_QUERY)
            content = json.loads(response.content)
            # Partial errors expected (Value.updatedDate raises for anonymous)
            self.assertIn("data", content)
            self._validate_response(content, [], "unauthenticated", is_staff=False, is_authenticated=False)

        # Query 3: regular (authenticated, no perms)
        username = self._create_user([], 98)
        self.client.login(username=username, password=TEST_USER_PASSWORD)
        with self.subTest(permissions="no perms"):
            response = self.query(FIELD_PERM_QUERY)
            self.assertResponseNoErrors(response)
            content = json.loads(response.content)
            self._validate_response(content, [], "no perms", is_staff=False, is_authenticated=True)

        # Queries 4-19: all 16 permission combos
        for i, perms in enumerate(self.perm_combos):
            label = ", ".join(perms) if perms else "no perms (combo)"
            with self.subTest(permissions=label):
                username = self._create_user(perms, i)
                self.client.login(username=username, password=TEST_USER_PASSWORD)
                response = self.query(FIELD_PERM_QUERY)
                self.assertResponseNoErrors(response)
                content = json.loads(response.content)
                self._validate_response(content, perms, label, is_staff=False, is_authenticated=True)
