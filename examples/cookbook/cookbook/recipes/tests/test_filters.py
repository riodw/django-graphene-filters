import json

from cookbook.recipes.models import Object, ObjectType
from cookbook.recipes.services import create_people
from graphene_django.utils import GraphQLTestCase


class FilterTests(GraphQLTestCase):
    def setUp(self):
        super().setUp()
        # Ensure clean state
        Object.objects.all().delete()
        ObjectType.objects.all().delete()

        # Create test data using the service to ensure consistent structure
        create_people(3)
        self.person_type = ObjectType.objects.get(name="People")

    def test_filter_by_object_type(self):
        """Test filtering by object type name using nested filter structure."""
        response = self.query("""
            query {
              allObjects(filter: { objectType: { name: { exact: "People" } } }) {
                edges {
                  node {
                    id
                    objectType {
                      name
                    }
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), 3)
        for edge in edges:
            self.assertEqual(edge["node"]["objectType"]["name"], "People")

    def test_filter_by_attribute_value(self):
        """Test filtering objects by their attribute values (e.g. finding everyone with a specific email)."""
        # Get a specific value to query for
        person = Object.objects.filter(object_type=self.person_type).first()
        # Find the email value
        email_val = person.values.filter(attribute__name="Email").first()

        response = self.query(f"""
            query {{
              allObjects(filter: {{
                values: {{
                  attribute: {{ name: {{ exact: "Email" }} }},
                  value: {{ exact: "{email_val.value}" }}
                }}
              }}) {{
                edges {{
                  node {{
                    id
                    name
                  }}
                }}
              }}
            }}
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        # Should match at least one person (the one we picked)
        self.assertGreaterEqual(len(edges), 1)
        # Verify the matched person is in the results
        matched_ids = [e["node"]["id"] for e in edges]
        # In Graphene Django, global IDs are base64 encoded "Type:ID"
        from graphql_relay import to_global_id

        expected_id = to_global_id("ObjectNode", person.id)
        self.assertIn(expected_id, matched_ids)

    def test_filter_and_logic(self):
        """Test AND logic in filtering."""
        response = self.query("""
            query {
              allObjects(filter: {
                and: [
                    { objectType: { name: { exact: "People" } } },
                    { name: { icontains: "" } } # All names are non-empty
                ]
              }) {
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
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        # All created people have a name
        self.assertEqual(len(edges), 3)

    def test_filter_or_logic(self):
        """Test OR logic in filtering."""
        # Create a non-person object to test OR
        other_type = ObjectType.objects.create(name="Other")
        Object.objects.create(name="Thing", object_type=other_type)

        response = self.query("""
            query {
              allObjects(filter: {
                or: [
                    { objectType: { name: { exact: "People" } } },
                    { objectType: { name: { exact: "Other" } } }
                ]
              }) {
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
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        # 3 People + 1 Other = 4 total
        self.assertEqual(len(edges), 4)

    def test_filter_not_logic(self):
        """Test NOT logic in filtering."""
        response = self.query("""
            query {
              allObjects(filter: {
                not: { objectType: { name: { exact: "People" } } }
              }) {
                edges {
                  node {
                    id
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        # Should be 0 since we only have "People" in setUp
        self.assertEqual(len(edges), 0)
