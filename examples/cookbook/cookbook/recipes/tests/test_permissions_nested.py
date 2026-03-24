import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import TEST_USER_PASSWORD, create_users, seed_data
from graphene_django.utils import GraphQLTestCase

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


class ObjectPermissionTests(GraphQLTestCase):
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

    def test_staff_sees_all_objects(self):
        self.client.login(username="staff_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total)

    def test_non_staff_sees_public_objects(self):
        """Non-staff users see public objects but no cascade — nested FK nulls may occur."""
        self.client.login(username="regular_1", password=TEST_USER_PASSWORD)

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

    def test_not_authenticated_cascade_permissions(self):
        """Unauthenticated users get cascade permissions — no private data at any depth."""
        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]

        # Every returned object must have isPrivate=False
        for edge in edges:
            node = edge["node"]
            self.assertFalse(
                node["isPrivate"],
                f"Unauthenticated user received private Object: {node['name']}",
            )

            # Root-level objectType must not be private
            self.assertFalse(
                node["objectType"]["isPrivate"],
                f"Unauthenticated user received private ObjectType: {node['objectType']['name']} "
                f"on Object: {node['name']}",
            )

            # Nested values must not be private
            for value_edge in node["values"]["edges"]:
                value_node = value_edge["node"]
                self.assertFalse(
                    value_node["isPrivate"],
                    f"Unauthenticated user received private Value: {value_node['value']} "
                    f"on Object: {node['name']}",
                )

                # Nested attribute must not be private
                attr = value_node["attribute"]
                self.assertFalse(
                    attr["isPrivate"],
                    f"Unauthenticated user received private Attribute: {attr['name']} "
                    f"on Value: {value_node['value']}",
                )

                # Attribute's objectType must not be private
                self.assertFalse(
                    attr["objectType"]["isPrivate"],
                    f"Unauthenticated user received private ObjectType: {attr['objectType']['name']} "
                    f"on Attribute: {attr['name']}",
                )
