import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import seed_data
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()

COUNT = 4

ALL_OBJECTS_QUERY = """
    query MyQuery {
      allObjects {
        edges {
          node {
            name
            id
            isPrivate
            objectType {
              id
              name
              isPrivate
            }
          }
        }
      }
    }
"""


class ObjectPermissionTests(GraphQLTestCase):
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
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total)

    def test_non_staff_cannot_see_private_objects(self):
        User.objects.create_user(username="regular", password="testpass", is_staff=False)
        self.client.login(username="regular", password="testpass")

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total - self.private_count)

        # Every returned object must have isPrivate=False
        for edge in edges:
            node = edge["node"]
            self.assertFalse(
                node["isPrivate"],
                f"Non-staff user received private Object: {node['name']}",
            )

            # Root-level objectType must not be private
            self.assertFalse(
                node["objectType"]["isPrivate"],
                f"Non-staff user received private ObjectType: {node['objectType']['name']} "
                f"on Object: {node['name']}",
            )
