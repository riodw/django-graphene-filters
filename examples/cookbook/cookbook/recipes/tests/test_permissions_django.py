"""Tests for Django built-in user_permissions integration.

Each model has an auto-generated ``view_<model>`` permission created by
``django.contrib.auth``.  Granting that permission to a non-staff user gives
them the same full visibility that ``is_staff=True`` provides.

Three user types are tested per model (4 models x 3 tests = 12 tests):
1. Staff (is_staff=True)              → sees ALL rows
2. Non-staff, no permissions          → sees only is_private=False
3. Non-staff, with view_<model> perm  → sees ALL rows
"""

import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import TEST_USER_PASSWORD, create_users, seed_data
from graphene_django.utils import GraphQLTestCase

COUNT = 4

ALL_OBJECT_TYPES_QUERY = """
    query {
      allObjectTypes {
        edges {
          node {
            id
            name
          }
        }
      }
    }
"""

ALL_OBJECTS_QUERY = """
    query {
      allObjects {
        edges {
          node {
            id
            name
          }
        }
      }
    }
"""

ALL_ATTRIBUTES_QUERY = """
    query($cursor: String) {
      allAttributes(first: 100, after: $cursor) {
        edges {
          node {
            id
            name
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
"""

ALL_VALUES_QUERY = """
    query($cursor: String) {
      allValues(first: 100, after: $cursor) {
        edges {
          node {
            id
            value
          }
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
"""


def _paginate_all(test_case, query, root_field):
    """Fetch all records through Relay pagination (100 per page)."""
    all_edges = []
    cursor = None

    while True:
        variables = json.dumps({"cursor": cursor})
        response = test_case.query(query, variables=variables)
        test_case.assertResponseNoErrors(response)
        content = json.loads(response.content)

        data = content["data"][root_field]
        all_edges.extend(data["edges"])

        if not data["pageInfo"]["hasNextPage"]:
            break
        cursor = data["pageInfo"]["endCursor"]

    return all_edges


class ObjectTypeDjangoPermissionTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)
        create_users()

        self.total = ObjectType.objects.count()
        self.private_count = ObjectType.objects.filter(is_private=True).count()

    def test_staff_sees_all_object_types(self):
        self.client.login(username="staff_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECT_TYPES_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjectTypes"]["edges"]
        self.assertEqual(len(edges), self.total)

    def test_non_staff_no_perms_sees_public_only(self):
        self.client.login(username="regular_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECT_TYPES_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjectTypes"]["edges"]
        self.assertEqual(len(edges), self.total - self.private_count)

    def test_non_staff_with_view_perm_sees_public_only(self):
        """view_objecttype perm users see only public ObjectTypes."""
        self.client.login(username="view_objecttype_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECT_TYPES_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjectTypes"]["edges"]
        self.assertEqual(len(edges), self.total - self.private_count)


class ObjectDjangoPermissionTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)
        create_users()

        self.total = Object.objects.count()
        self.private_count = Object.objects.filter(is_private=True).count()
        # Cascade-aware count: public Objects whose ObjectType is also public
        visible_ot_ids = ObjectType.objects.filter(is_private=False).values_list("id", flat=True)
        self.cascade_public_count = Object.objects.filter(
            is_private=False, object_type_id__in=visible_ot_ids
        ).count()

    def test_staff_sees_all_objects(self):
        self.client.login(username="staff_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total)

    def test_non_staff_no_perms_sees_public_only(self):
        """Regular users see only public Objects whose ObjectType is also public (cascade)."""
        self.client.login(username="regular_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.cascade_public_count)

    def test_non_staff_with_view_perm_sees_public_only(self):
        """view_object perm users see all public Objects (no cascade)."""
        self.client.login(username="view_object_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total - self.private_count)


class AttributeDjangoPermissionTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)
        create_users()

        self.total = Attribute.objects.count()
        self.private_count = Attribute.objects.filter(is_private=True).count()
        # Cascade-aware count: public Attributes whose ObjectType is also public
        visible_ot_ids = ObjectType.objects.filter(is_private=False).values_list("id", flat=True)
        self.cascade_public_count = Attribute.objects.filter(
            is_private=False, object_type_id__in=visible_ot_ids
        ).count()

    def test_staff_sees_all_attributes(self):
        self.client.login(username="staff_1", password=TEST_USER_PASSWORD)

        edges = _paginate_all(self, ALL_ATTRIBUTES_QUERY, "allAttributes")
        self.assertEqual(len(edges), self.total)

    def test_non_staff_no_perms_sees_public_only(self):
        """Regular users see only public Attributes whose ObjectType is also public (cascade)."""
        self.client.login(username="regular_1", password=TEST_USER_PASSWORD)

        edges = _paginate_all(self, ALL_ATTRIBUTES_QUERY, "allAttributes")
        self.assertEqual(len(edges), self.cascade_public_count)

    def test_non_staff_with_view_perm_sees_public_only(self):
        """view_attribute perm users see only public Attributes (no cascade)."""
        self.client.login(username="view_attribute_1", password=TEST_USER_PASSWORD)

        edges = _paginate_all(self, ALL_ATTRIBUTES_QUERY, "allAttributes")
        self.assertEqual(len(edges), self.total - self.private_count)


class ValueDjangoPermissionTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)
        create_users()

        self.total = Value.objects.count()
        self.private_count = Value.objects.filter(is_private=True).count()
        # Cascade-aware count: public Values whose Attribute AND Object are also visible
        visible_ot_ids = ObjectType.objects.filter(is_private=False).values_list("id", flat=True)
        visible_attr_ids = Attribute.objects.filter(
            is_private=False, object_type_id__in=visible_ot_ids
        ).values_list("id", flat=True)
        visible_obj_ids = Object.objects.filter(
            is_private=False, object_type_id__in=visible_ot_ids
        ).values_list("id", flat=True)
        self.cascade_public_count = Value.objects.filter(
            is_private=False,
            attribute_id__in=visible_attr_ids,
            object_id__in=visible_obj_ids,
        ).count()

    def test_staff_sees_all_values(self):
        self.client.login(username="staff_1", password=TEST_USER_PASSWORD)

        edges = _paginate_all(self, ALL_VALUES_QUERY, "allValues")
        self.assertEqual(len(edges), self.total)

    def test_non_staff_no_perms_sees_public_only(self):
        """Regular users see only public Values whose Attribute and Object are also visible (cascade)."""
        self.client.login(username="regular_1", password=TEST_USER_PASSWORD)

        edges = _paginate_all(self, ALL_VALUES_QUERY, "allValues")
        self.assertEqual(len(edges), self.cascade_public_count)

    def test_non_staff_with_view_perm_sees_public_only(self):
        """view_value perm users see only public Values (no cascade)."""
        self.client.login(username="view_value_1", password=TEST_USER_PASSWORD)

        edges = _paginate_all(self, ALL_VALUES_QUERY, "allValues")
        self.assertEqual(len(edges), self.total - self.private_count)
