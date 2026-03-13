import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()


class SearchTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        # Ensure clean state
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        # Create deterministic test data
        self.people_type = ObjectType.objects.create(name="People", description="Human beings")
        self.vehicle_type = ObjectType.objects.create(name="Vehicles", description="Motorized transport")

        self.email_attr = Attribute.objects.create(
            name="Email", description="Electronic mail", object_type=self.people_type
        )
        self.city_attr = Attribute.objects.create(
            name="City", description="Home city", object_type=self.people_type
        )
        self.color_attr = Attribute.objects.create(
            name="Color", description="Paint color", object_type=self.vehicle_type
        )

        self.alice = Object.objects.create(
            name="Alice", description="Software engineer", object_type=self.people_type
        )
        self.bob = Object.objects.create(
            name="Bob", description="Mechanical engineer", object_type=self.people_type
        )
        self.truck = Object.objects.create(
            name="Ford F-150", description="Pickup truck", object_type=self.vehicle_type
        )

        Value.objects.create(value="alice@example.com", attribute=self.email_attr, object=self.alice)
        Value.objects.create(value="Denver", attribute=self.city_attr, object=self.alice)
        Value.objects.create(value="bob@example.com", attribute=self.email_attr, object=self.bob)
        Value.objects.create(value="Austin", attribute=self.city_attr, object=self.bob)
        Value.objects.create(value="Red", attribute=self.color_attr, object=self.truck)

    def _get_edges(self, response):
        content = json.loads(response.content)
        if "errors" in content:
            raise Exception(f"GraphQL Errors: {content['errors']}")
        # Find the first top-level key under "data"
        data = content["data"]
        key = next(iter(data))
        return data[key]["edges"]

    def _get_names(self, edges):
        return [e["node"]["name"] for e in edges]

    # ------------------------------------------------------------------
    # Search on allObjects (search_fields: name, description,
    #                        object_type__name, object_type__description)
    # ------------------------------------------------------------------

    def test_search_objects_by_name(self):
        """Search for 'Alice' should match the Alice object by name."""
        response = self.query("""
            query {
              allObjects(search: "Alice") {
                edges {
                  node {
                    name
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        names = self._get_names(self._get_edges(response))
        self.assertIn("Alice", names)
        self.assertNotIn("Bob", names)

    def test_search_objects_by_description(self):
        """Search for 'engineer' should match both Alice and Bob via description."""
        response = self.query("""
            query {
              allObjects(search: "engineer") {
                edges {
                  node {
                    name
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        names = self._get_names(self._get_edges(response))
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)
        self.assertNotIn("Ford F-150", names)

    def test_search_objects_across_relation(self):
        """Search for 'Vehicles' should match the truck via object_type__name."""
        response = self.query("""
            query {
              allObjects(search: "Vehicles") {
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
            """)
        self.assertResponseNoErrors(response)
        names = self._get_names(self._get_edges(response))
        self.assertIn("Ford F-150", names)
        self.assertNotIn("Alice", names)

    def test_search_objects_no_results(self):
        """Search for a term that matches nothing should return empty."""
        response = self.query("""
            query {
              allObjects(search: "zzzznotfound") {
                edges {
                  node {
                    name
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        edges = self._get_edges(response)
        self.assertEqual(len(edges), 0)

    def test_search_objects_multiple_terms(self):
        """Multiple terms are ANDed: 'Software engineer' matches Alice only."""
        response = self.query("""
            query {
              allObjects(search: "Software engineer") {
                edges {
                  node {
                    name
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        names = self._get_names(self._get_edges(response))
        self.assertIn("Alice", names)
        self.assertNotIn("Bob", names)

    # ------------------------------------------------------------------
    # Search combined with filter and orderBy
    # ------------------------------------------------------------------

    def test_search_combined_with_filter(self):
        """Search + filter: search 'engineer', filter to People type only."""
        response = self.query("""
            query {
              allObjects(
                search: "engineer"
                filter: { objectType: { name: { exact: "People" } } }
              ) {
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
            """)
        self.assertResponseNoErrors(response)
        edges = self._get_edges(response)
        names = self._get_names(edges)
        self.assertIn("Alice", names)
        self.assertIn("Bob", names)
        for edge in edges:
            self.assertEqual(edge["node"]["objectType"]["name"], "People")

    def test_search_combined_with_order(self):
        """Search + orderBy: search 'engineer', order by name ASC."""
        response = self.query("""
            query {
              allObjects(
                search: "engineer"
                orderBy: [{ name: ASC }]
              ) {
                edges {
                  node {
                    name
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        names = self._get_names(self._get_edges(response))
        self.assertEqual(names, ["Alice", "Bob"])

    # ------------------------------------------------------------------
    # Search on allObjectTypes (search_fields: name, description)
    # ------------------------------------------------------------------

    def test_search_object_types_by_name(self):
        """Search ObjectTypes for 'People'."""
        response = self.query("""
            query {
              allObjectTypes(search: "People") {
                edges {
                  node {
                    name
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        names = self._get_names(self._get_edges(response))
        self.assertIn("People", names)
        self.assertNotIn("Vehicles", names)

    # ------------------------------------------------------------------
    # Search on allValues (search_fields: value, description,
    #                       attribute__name, object__name)
    # ------------------------------------------------------------------

    def test_search_values_by_attribute_name(self):
        """Search Values for 'Email' should match via attribute__name."""
        response = self.query("""
            query {
              allValues(search: "Email") {
                edges {
                  node {
                    value
                    attribute {
                      name
                    }
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        edges = self._get_edges(response)
        # Both alice and bob have email values
        self.assertEqual(len(edges), 2)
        for edge in edges:
            self.assertEqual(edge["node"]["attribute"]["name"], "Email")

    def test_search_values_by_object_name(self):
        """Search Values for 'Alice' should match via object__name."""
        response = self.query("""
            query {
              allValues(search: "Alice") {
                edges {
                  node {
                    value
                    object {
                      name
                    }
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        edges = self._get_edges(response)
        # Alice has 2 values (email + city)
        self.assertEqual(len(edges), 2)
        for edge in edges:
            self.assertEqual(edge["node"]["object"]["name"], "Alice")
