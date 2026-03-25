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
        # Cascade-aware count: public Objects whose ObjectType is also public
        visible_ot_ids = ObjectType.objects.filter(is_private=False).values_list("id", flat=True)
        self.cascade_public_count = Object.objects.filter(
            is_private=False, object_type_id__in=visible_ot_ids
        ).count()

    def test_staff_sees_all_objects(self):
        self.client.login(username="staff_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.total)

    def test_non_staff_sees_public_objects(self):
        """Regular users see only public Objects whose ObjectType is also public (cascade)."""
        self.client.login(username="regular_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), self.cascade_public_count)

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

    def test_view_object_user_object_type_id_consistency(self):
        """A view_object user sees public Objects with sentinels for hidden FKs.

        Every Object's top-level objectType and every nested
        attribute.objectType refer to the same ObjectType.  The sentinel
        preserves real FK IDs, so the ID must always match — even when
        the intermediate Attribute is a sentinel.
        """
        self.client.login(username="view_object_1", password=TEST_USER_PASSWORD)

        response = self.query(ALL_OBJECTS_QUERY)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]

        for edge in edges:
            node = edge["node"]
            root_object_type_id = node["objectType"]["id"]

            for value_edge in node["values"]["edges"]:
                attr = value_edge["node"]["attribute"]
                nested_object_type_id = attr["objectType"]["id"]

                self.assertEqual(
                    root_object_type_id,
                    nested_object_type_id,
                    f"ObjectType ID mismatch on Object '{node['name']}': "
                    f"root objectType={root_object_type_id}, "
                    f"attribute '{attr['name']}' objectType={nested_object_type_id}",
                )
