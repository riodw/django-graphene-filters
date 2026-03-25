"""Dynamic permission combination tests.

Fires 17 queries total: 1 unauthenticated + all 16 combinations of the
4 model-level view permissions (2^4 = 16). Each query uses the same
deeply-nested allObjects query and validates:

1. Root Object count matches the expected cascade/non-cascade count.
2. No private data (isPrivate=True) appears at any depth — root Objects,
   objectType, values, attributes, or attribute.objectType.
3. No unexpected sentinels where cascade guarantees visibility.

Excluded user types (tested elsewhere):
- is_staff=True
"""

import itertools
import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import TEST_USER_PASSWORD, seed_data
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from graphene_django.utils import GraphQLTestCase

COUNT = 4

# The 4 model-level view permissions to combine.
VIEW_PERMISSIONS = [
    "view_objecttype",
    "view_object",
    "view_attribute",
    "view_value",
]

# Maps GraphQL field names to the view permission of the target model.
# Used by _walk_node to determine cascade state at each depth.
FIELD_TO_PERM = {
    "objectType": "view_objecttype",
    "values": "view_value",
    "attribute": "view_attribute",
    "object": "view_object",
}

# Same deeply-nested query used in test_permissions_nested.py.
ALL_OBJECTS_QUERY = """
    query MyQuery {
      allObjects {
        edges {
          node {
            name
            id
            isPrivate
            objectType {
              name
              isPrivate
              id
            }
            values {
              edges {
                node {
                  isPrivate
                  value
                  id
                  attribute {
                    name
                    isPrivate
                    id
                    objectType {
                      name
                      isPrivate
                      id
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


class PermissionCombinationTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        # Pre-compute the two possible root Object counts.
        # With view_object perm: public Objects only (no cascade).
        self.public_object_count = Object.objects.filter(is_private=False).count()

        # Without view_object perm: cascade — public Objects whose ObjectType
        # is also public. (ObjectType cascade is a no-op since it has no FKs.)
        visible_ot_ids = ObjectType.objects.filter(is_private=False).values_list("id", flat=True)
        self.cascade_object_count = Object.objects.filter(
            is_private=False, object_type_id__in=visible_ot_ids
        ).count()

        # Generate all 16 permission combinations (powerset of VIEW_PERMISSIONS).
        self.perm_combos = []
        for r in range(len(VIEW_PERMISSIONS) + 1):
            for combo in itertools.combinations(VIEW_PERMISSIONS, r):
                self.perm_combos.append(list(combo))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_user(self, perms, index):
        """Create and return the username of a non-staff user with ``perms``."""
        User = get_user_model()
        username = f"combo_{index}"
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

    def _expected_object_count(self, perms):
        """Return the expected root Object count for a given permission set."""
        if "view_object" in perms:
            return self.public_object_count
        return self.cascade_object_count

    def _walk_node(self, node, node_perm, guaranteed_visible, perms, label, path):
        """Recursively validate a single node in the response tree.

        Works regardless of query depth — handles any combination of FK
        fields (plain dicts) and connection fields (dicts with ``edges``).

        Args:
            node: The GraphQL node dict to validate.
            node_perm: The ``view_*`` permission codename that controls
                this node's model visibility.
            guaranteed_visible: ``True`` when a parent's cascade already
                ensured this node is visible (i.e. must not be a sentinel).
            perms: The current user's permission set.
            label: Human-readable permission combo label for error messages.
            path: Dot-separated path for error context (e.g. ``Object.objectType``).
        """
        # 1. isPrivate must always be False (filtering + sentinel defaults).
        if "isPrivate" in node:
            self.assertFalse(
                node["isPrivate"],
                f"[{label}] isPrivate=True at {path}",
            )

        # 2. Detect sentinel: model defaults leave name/value as "".
        #    If the query didn't request a text field we can't detect
        #    sentinels — gracefully skip.
        if "name" in node:
            is_sentinel = node["name"] == ""
        elif "value" in node:
            is_sentinel = node["value"] == ""
        else:
            is_sentinel = False

        if guaranteed_visible and is_sentinel:
            self.fail(f"[{label}] Unexpected sentinel at {path}")

        # 3. Cascade state for THIS node's FK children.
        #    Active when the node is real (not a sentinel) and the
        #    user lacks the model's view permission.
        cascade_active = (not is_sentinel) and (node_perm not in perms)

        # 4. Recurse into child fields present in the response.
        for field_name, child_perm in FIELD_TO_PERM.items():
            if field_name not in node:
                continue
            child = node[field_name]
            child_path = f"{path}.{field_name}"

            if isinstance(child, dict) and "edges" in child:
                # Connection field — each child is a real DB row returned
                # by the child type's get_queryset.
                for j, edge in enumerate(child["edges"]):
                    self._walk_node(
                        edge["node"],
                        child_perm,
                        cascade_active,
                        perms,
                        label,
                        f"{child_path}[{j}]",
                    )
            elif isinstance(child, dict):
                # FK field — resolved via get_node; may be a sentinel.
                self._walk_node(
                    child,
                    child_perm,
                    cascade_active,
                    perms,
                    label,
                    child_path,
                )

    # ------------------------------------------------------------------
    # Test
    # ------------------------------------------------------------------

    def _run_query_and_validate(self, perms, label):
        """Execute the query and validate counts + response shape for a permission set."""
        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]

        # 1. Root Object count
        expected = self._expected_object_count(perms)
        self.assertEqual(
            len(edges),
            expected,
            f"[{label}] Root Object count: expected {expected}, got {len(edges)}",
        )

        # 2. Recursive shape check — no private data, no
        #    unexpected sentinels at any depth.
        for j, edge in enumerate(edges):
            self._walk_node(
                edge["node"],
                "view_object",
                True,
                perms,
                label,
                f"Object[{j}]",
            )

    def test_all_permission_combinations(self):
        """Fire 17 queries: 1 unauthenticated + 16 permission combos."""
        self.assertEqual(len(self.perm_combos), 16)

        # Query 1: unauthenticated user (not logged in, no session)
        self.client.logout()
        with self.subTest(permissions="unauthenticated"):
            self._run_query_and_validate([], "unauthenticated")

        # Queries 2–17: authenticated users with each permission combo
        for i, perms in enumerate(self.perm_combos):
            label = ", ".join(perms) if perms else "no perms"

            with self.subTest(permissions=label):
                username = self._create_user(perms, i)
                self.client.login(username=username, password=TEST_USER_PASSWORD)
                self._run_query_and_validate(perms, label)
