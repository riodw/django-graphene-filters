import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()


class OrderingTests(GraphQLTestCase):
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
        self.animal_type = ObjectType.objects.create(name="Animals", description="Living creatures")
        self.plant_type = ObjectType.objects.create(name="Plants", description="Botanical organisms")

        self.color_attr = Attribute.objects.create(
            name="Color", description="Primary color", object_type=self.animal_type
        )
        self.height_attr = Attribute.objects.create(
            name="Height", description="How tall", object_type=self.plant_type
        )

        # Objects with deliberate names for sort testing
        self.cat = Object.objects.create(
            name="Cat", description="Small feline", object_type=self.animal_type
        )
        self.dog = Object.objects.create(
            name="Dog", description="Loyal canine", object_type=self.animal_type
        )
        self.ant = Object.objects.create(
            name="Ant", description="Tiny insect", object_type=self.animal_type
        )
        self.fern = Object.objects.create(
            name="Fern", description="Ancient plant", object_type=self.plant_type
        )
        self.bamboo = Object.objects.create(
            name="Bamboo", description="Fast grower", object_type=self.plant_type
        )

        # Values
        Value.objects.create(value="Orange", attribute=self.color_attr, object=self.cat)
        Value.objects.create(value="Brown", attribute=self.color_attr, object=self.dog)
        Value.objects.create(value="Black", attribute=self.color_attr, object=self.ant)
        Value.objects.create(value="3ft", attribute=self.height_attr, object=self.fern)
        Value.objects.create(value="60ft", attribute=self.height_attr, object=self.bamboo)

    def _get_edges(self, response):
        content = json.loads(response.content)
        if "errors" in content:
            raise Exception(f"GraphQL Errors: {content['errors']}")
        data = content["data"]
        key = next(iter(data))
        return data[key]["edges"]

    def _get_names(self, edges):
        return [e["node"]["name"] for e in edges]

    # ------------------------------------------------------------------
    # Basic ordering on a flat field
    # ------------------------------------------------------------------

    def test_order_objects_by_name_asc(self):
        response = self.query("""
            query {
              allObjects(orderBy: [{ name: ASC }]) {
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
        self.assertEqual(names, ["Ant", "Bamboo", "Cat", "Dog", "Fern"])

    def test_order_objects_by_name_desc(self):
        response = self.query("""
            query {
              allObjects(orderBy: [{ name: DESC }]) {
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
        self.assertEqual(names, ["Fern", "Dog", "Cat", "Bamboo", "Ant"])

    def test_order_object_types_by_name_asc(self):
        response = self.query("""
            query {
              allObjectTypes(orderBy: [{ name: ASC }]) {
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
        self.assertEqual(names, ["Animals", "Plants"])

    def test_order_object_types_by_name_desc(self):
        response = self.query("""
            query {
              allObjectTypes(orderBy: [{ name: DESC }]) {
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
        self.assertEqual(names, ["Plants", "Animals"])

    def test_order_by_description(self):
        response = self.query("""
            query {
              allObjectTypes(orderBy: [{ description: ASC }]) {
                edges {
                  node {
                    name
                    description
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        edges = self._get_edges(response)
        descriptions = [e["node"]["description"] for e in edges]
        self.assertEqual(descriptions, sorted(descriptions))

    # ------------------------------------------------------------------
    # Ordering across relationships
    # ------------------------------------------------------------------

    def test_order_objects_by_related_object_type_name_asc(self):
        """Order objects by object_type.name ASC, then by name ASC."""
        response = self.query("""
            query {
              allObjects(orderBy: [{ objectType: { name: ASC } }, { name: ASC }]) {
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
        # Animals first (Ant, Cat, Dog), then Plants (Bamboo, Fern)
        self.assertEqual(names, ["Ant", "Cat", "Dog", "Bamboo", "Fern"])

    def test_order_objects_by_related_object_type_name_desc(self):
        """Order objects by object_type.name DESC, then by name ASC."""
        response = self.query("""
            query {
              allObjects(orderBy: [{ objectType: { name: DESC } }, { name: ASC }]) {
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
        # Plants first (Bamboo, Fern), then Animals (Ant, Cat, Dog)
        self.assertEqual(names, ["Bamboo", "Fern", "Ant", "Cat", "Dog"])

    def test_order_values_by_related_attribute_name(self):
        """Order values by attribute.name ASC."""
        response = self.query("""
            query {
              allValues(orderBy: [{ attribute: { name: ASC } }]) {
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
        attr_names = [e["node"]["attribute"]["name"] for e in edges]
        # Color (3 values) before Height (2 values)
        self.assertEqual(attr_names[:3], ["Color", "Color", "Color"])
        self.assertEqual(attr_names[3:], ["Height", "Height"])

    # ------------------------------------------------------------------
    # Ordering combined with filter
    # ------------------------------------------------------------------

    def test_order_with_filter(self):
        """Filter to Animals only, then order by name DESC."""
        response = self.query("""
            query {
              allObjects(
                filter: { objectType: { name: { exact: "Animals" } } }
                orderBy: [{ name: DESC }]
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
        self.assertEqual(names, ["Dog", "Cat", "Ant"])

    def test_order_with_search(self):
        """Search for 'an' (matches Ant, Ancient plant -> Fern), order by name ASC."""
        response = self.query("""
            query {
              allObjects(
                search: "an"
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
        # All results should be sorted ASC
        self.assertEqual(names, sorted(names))
        # "Ant" matches by name, "Fern" matches by description "Ancient plant"
        self.assertIn("Ant", names)
        self.assertIn("Fern", names)

    # ------------------------------------------------------------------
    # No ordering (default / unordered)
    # ------------------------------------------------------------------

    def test_no_order_returns_all(self):
        """Without orderBy, all objects should still be returned."""
        response = self.query("""
            query {
              allObjects {
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
        self.assertEqual(len(names), 5)

    # ------------------------------------------------------------------
    # Combined filter + search + order
    # ------------------------------------------------------------------

    def test_order_values_by_value_asc(self):
        """ValueOrder has fields=["value"], so ordering by value should work."""
        response = self.query("""
            query {
              allValues(orderBy: [{ value: ASC }]) {
                edges {
                  node {
                    value
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        edges = self._get_edges(response)
        values = [e["node"]["value"] for e in edges]
        self.assertEqual(values, sorted(values))

    def test_order_values_by_description_is_ignored(self):
        """ValueOrder has fields=["value"] — description is excluded.

        Attempting to order by description should be silently ignored
        (the field doesn't exist in the schema), so this query should error.
        """
        response = self.query("""
            query {
              allValues(orderBy: [{ description: ASC }]) {
                edges {
                  node {
                    value
                  }
                }
              }
            }
            """)
        content = json.loads(response.content)
        # description is not in the ValueOrder schema, so GraphQL should reject it
        self.assertIn("errors", content)

    def test_filter_search_and_order_combined(self):
        """Filter to Animals, search for 'in' (feline, canine, insect), order by name DESC."""
        response = self.query("""
            query {
              allObjects(
                filter: { objectType: { name: { exact: "Animals" } } }
                search: "in"
                orderBy: [{ name: DESC }]
              ) {
                edges {
                  node {
                    name
                    description
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        names = self._get_names(self._get_edges(response))
        # "Small feline" -> Cat, "Loyal canine" -> Dog, "Tiny insect" -> Ant
        # All contain "in" in their description; ordered DESC
        self.assertEqual(names, sorted(names, reverse=True))
        for name in names:
            self.assertIn(name, ["Cat", "Dog", "Ant"])
