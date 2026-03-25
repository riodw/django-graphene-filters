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

    def test_non_staff_cannot_see_private_objects(self):
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

            # Root-level objectType must not be private
            self.assertFalse(
                node["objectType"]["isPrivate"],
                f"Non-staff user received private ObjectType: {node['objectType']['name']} "
                f"on Object: {node['name']}",
            )
