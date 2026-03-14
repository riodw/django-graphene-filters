import json

from cookbook.recipes.models import Object, ObjectType
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()


class GetQuerysetPermissionTests(GraphQLTestCase):
    """Tests for ObjectNode.get_queryset which hides 'Secret' objects from non-staff users.

    ObjectNode.get_queryset excludes objects whose object_type__name == "Secret"
    when the request user is not staff.  Staff users see everything.
    """

    GRAPHQL_URL = "/graphql/"

    ALL_OBJECTS_QUERY = """
        query {
          allObjects {
            edges {
              node {
                name
                objectType {
                  name
                }
              }
            }
          }
        }
    """

    def setUp(self):
        super().setUp()

        Object.objects.all().delete()
        ObjectType.objects.all().delete()

        # Two object types: one normal, one secret
        self.public_type = ObjectType.objects.create(name="People", description="Normal type")
        self.secret_type = ObjectType.objects.create(name="Secret", description="Hidden type")

        # Objects of each type
        Object.objects.create(name="Alice", object_type=self.public_type)
        Object.objects.create(name="Bob", object_type=self.public_type)
        Object.objects.create(name="ClassifiedAgent", object_type=self.secret_type)

        # Users
        self.staff_user = User.objects.create_user(username="admin", password="testpass", is_staff=True)
        self.regular_user = User.objects.create_user(username="regular", password="testpass", is_staff=False)

    # -----------------------------------------------------------------
    # Anonymous user
    # -----------------------------------------------------------------

    def test_anonymous_user_cannot_see_secret_objects(self):
        """An anonymous (not logged in) user should not see Secret objects."""
        self.client.logout()
        response = self.query(self.ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        names = [e["node"]["name"] for e in edges]
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)
        self.assertNotIn("ClassifiedAgent", names)
        self.assertEqual(len(edges), 2)

    # -----------------------------------------------------------------
    # Regular (non-staff) user
    # -----------------------------------------------------------------

    def test_regular_user_cannot_see_secret_objects(self):
        """A logged-in non-staff user should not see Secret objects."""
        self.client.login(username="regular", password="testpass")
        response = self.query(self.ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        names = [e["node"]["name"] for e in edges]
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)
        self.assertNotIn("ClassifiedAgent", names)
        self.assertEqual(len(edges), 2)

    def test_regular_user_filtering_for_secret_returns_nothing(self):
        """A non-staff user filtering by object_type description 'Hidden' gets nothing.

        Note: we filter by description (not name) because ObjectTypeFilter has a
        check_name_permission that blocks non-staff users from filtering by name.
        """
        self.client.login(username="regular", password="testpass")
        response = self.query("""
            query {
              allObjects(filter: { objectType: { description: { exact: "Hidden type" } } }) {
                edges {
                  node {
                    name
                  }
                }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), 0)

    def test_regular_user_searching_for_secret_object_returns_nothing(self):
        """A non-staff user searching for 'ClassifiedAgent' should get nothing."""
        self.client.login(username="regular", password="testpass")
        response = self.query("""
            query {
              allObjects(search: "ClassifiedAgent") {
                edges {
                  node {
                    name
                  }
                }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), 0)

    # -----------------------------------------------------------------
    # Staff user
    # -----------------------------------------------------------------

    def test_staff_user_can_see_all_objects(self):
        """A staff user should see both public and Secret objects."""
        self.client.login(username="admin", password="testpass")
        response = self.query(self.ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        names = [e["node"]["name"] for e in edges]
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)
        self.assertIn("ClassifiedAgent", names)
        self.assertEqual(len(edges), 3)

    def test_staff_user_can_filter_for_secret_objects(self):
        """A staff user filtering by object_type 'Secret' should see the secret object."""
        self.client.login(username="admin", password="testpass")
        response = self.query("""
            query {
              allObjects(filter: { objectType: { name: { exact: "Secret" } } }) {
                edges {
                  node {
                    name
                  }
                }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        names = [e["node"]["name"] for e in edges]
        self.assertEqual(names, ["ClassifiedAgent"])

    def test_staff_user_can_search_for_secret_object(self):
        """A staff user searching for 'ClassifiedAgent' should find it."""
        self.client.login(username="admin", password="testpass")
        response = self.query("""
            query {
              allObjects(search: "ClassifiedAgent") {
                edges {
                  node {
                    name
                  }
                }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        names = [e["node"]["name"] for e in edges]
        self.assertEqual(names, ["ClassifiedAgent"])
