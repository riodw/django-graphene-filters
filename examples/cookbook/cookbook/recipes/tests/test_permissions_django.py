"""Tests for Django built-in user_permissions integration.

Each model has an auto-generated ``view_<model>`` permission created by
``django.contrib.auth``.  Granting that permission to a non-staff user gives
them the same full visibility that ``is_staff=True`` provides.

Three user types are tested per model (4 models × 3 tests = 12 tests):
1. Staff (is_staff=True)              → sees ALL rows
2. Non-staff, no permissions          → sees only is_private=False
3. Non-staff, with view_<model> perm  → sees ALL rows
"""

import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import seed_data
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from graphene_django.utils import GraphQLTestCase

User = get_user_model()

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


def _grant_perm(user, codename):
    """Add a single permission to a user and return a fresh copy (clears perm cache)."""
    permission = Permission.objects.get(codename=codename)
    user.user_permissions.add(permission)
    # Re-fetch to clear Django's in-process permission cache
    return User.objects.get(pk=user.pk)


class ObjectTypeDjangoPermissionTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        self.total = ObjectType.objects.count()
        self.private_count = ObjectType.objects.filter(is_private=True).count()

    def test_staff_sees_all_object_types(self):
        User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        response = self.query(ALL_OBJECT_TYPES_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjectTypes"]["edges"]
        self.assertEqual(len(edges), self.total)

    def test_non_staff_no_perms_sees_public_only(self):
        User.objects.create_user(username="regular", password="testpass", is_staff=False)
        self.client.login(username="regular", password="testpass")

        response = self.query(ALL_OBJECT_TYPES_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjectTypes"]["edges"]
        self.assertEqual(len(edges), self.total - self.private_count)

    def test_non_staff_with_view_perm_sees_all(self):
        user = User.objects.create_user(username="granted", password="testpass", is_staff=False)
        user = _grant_perm(user, "view_objecttype")
        self.client.login(username="granted", password="testpass")

        response = self.query(ALL_OBJECT_TYPES_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjectTypes"]["edges"]
        self.assertEqual(len(edges), self.total)


class ObjectDjangoPermissionTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        self.total = Object.objects.count()
        self.private_count = Object.objects.filter(is_private=True).count()

    def test_staff_sees_all_objects(self):
        User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total)

    def test_non_staff_no_perms_sees_public_only(self):
        User.objects.create_user(username="regular", password="testpass", is_staff=False)
        self.client.login(username="regular", password="testpass")

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total - self.private_count)

    def test_non_staff_with_view_perm_sees_all(self):
        user = User.objects.create_user(username="granted", password="testpass", is_staff=False)
        user = _grant_perm(user, "view_object")
        self.client.login(username="granted", password="testpass")

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        edges = json.loads(response.content)["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total)


class AttributeDjangoPermissionTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        self.total = Attribute.objects.count()
        self.private_count = Attribute.objects.filter(is_private=True).count()

    def test_staff_sees_all_attributes(self):
        User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        edges = _paginate_all(self, ALL_ATTRIBUTES_QUERY, "allAttributes")
        self.assertEqual(len(edges), self.total)

    def test_non_staff_no_perms_sees_public_only(self):
        User.objects.create_user(username="regular", password="testpass", is_staff=False)
        self.client.login(username="regular", password="testpass")

        edges = _paginate_all(self, ALL_ATTRIBUTES_QUERY, "allAttributes")
        self.assertEqual(len(edges), self.total - self.private_count)

    def test_non_staff_with_view_perm_sees_all(self):
        user = User.objects.create_user(username="granted", password="testpass", is_staff=False)
        user = _grant_perm(user, "view_attribute")
        self.client.login(username="granted", password="testpass")

        edges = _paginate_all(self, ALL_ATTRIBUTES_QUERY, "allAttributes")
        self.assertEqual(len(edges), self.total)


class ValueDjangoPermissionTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        seed_data(COUNT)

        self.total = Value.objects.count()
        self.private_count = Value.objects.filter(is_private=True).count()

    def test_staff_sees_all_values(self):
        User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        edges = _paginate_all(self, ALL_VALUES_QUERY, "allValues")
        self.assertEqual(len(edges), self.total)

    def test_non_staff_no_perms_sees_public_only(self):
        User.objects.create_user(username="regular", password="testpass", is_staff=False)
        self.client.login(username="regular", password="testpass")

        edges = _paginate_all(self, ALL_VALUES_QUERY, "allValues")
        self.assertEqual(len(edges), self.total - self.private_count)

    def test_non_staff_with_view_perm_sees_all(self):
        user = User.objects.create_user(username="granted", password="testpass", is_staff=False)
        user = _grant_perm(user, "view_value")
        self.client.login(username="granted", password="testpass")

        edges = _paginate_all(self, ALL_VALUES_QUERY, "allValues")
        self.assertEqual(len(edges), self.total)
