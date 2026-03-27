import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.tests.test_existing import _create_people
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()


class FilterTests(GraphQLTestCase):
    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        # Authenticate as staff to satisfy filter permission checks
        self.staff_user = User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        # Ensure clean state
        Object.objects.all().delete()
        ObjectType.objects.all().delete()

        # Create test data using the service to ensure consistent structure
        _create_people(3)
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


class AutoDeriveQuerysetFilterTests(GraphQLTestCase):
    """Tests that RelatedFilter auto-derives queryset from the target filterset's model
    when no explicit queryset is provided, and that all nested filtering still works.
    """

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        self.obj_type = ObjectType.objects.create(name="Things", description="Stuff")
        self.attr_a = Attribute.objects.create(
            name="AttrA", description="First attribute", object_type=self.obj_type
        )
        self.attr_b = Attribute.objects.create(
            name="AttrB", description="Second attribute", object_type=self.obj_type
        )
        self.obj = Object.objects.create(name="Widget", description="A widget", object_type=self.obj_type)
        Value.objects.create(value="val_a", attribute=self.attr_a, object=self.obj)
        Value.objects.create(value="val_b", attribute=self.attr_b, object=self.obj)

    def test_auto_derived_queryset_filters_by_nested_attribute(self):
        """RelatedFilter without explicit queryset should still support nested filtering."""
        response = self.query("""
            query {
              allValues(filter: { attribute: { name: { exact: "AttrA" } } }) {
                edges {
                  node {
                    value
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allValues"]["edges"]
        values = [e["node"]["value"] for e in edges]
        self.assertEqual(values, ["val_a"])

    def test_auto_derived_queryset_returns_all_when_unfiltered(self):
        """Without any attribute filter, all values should be returned."""
        response = self.query("""
            query {
              allValues {
                edges {
                  node {
                    value
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allValues"]["edges"]
        self.assertEqual(len(edges), 2)


class ExplicitQuerysetFilterTests(GraphQLTestCase):
    """Tests that an explicit queryset on RelatedFilter acts as a scope boundary.

    ValueFilter.attribute has queryset=Attribute.objects.exclude(name="Secret").
    Values linked to a "Secret" attribute should never appear in results, even
    when the user explicitly filters for them.
    """

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        self.obj_type = ObjectType.objects.create(name="Gadgets")
        self.public_attr = Attribute.objects.create(
            name="Color", description="Visible attribute", object_type=self.obj_type
        )
        self.secret_attr = Attribute.objects.create(
            name="Secret", description="Hidden attribute", object_type=self.obj_type
        )
        self.obj = Object.objects.create(name="Gizmo", description="A gizmo", object_type=self.obj_type)
        # Two values: one public, one linked to the "Secret" attribute
        Value.objects.create(value="Red", attribute=self.public_attr, object=self.obj)
        Value.objects.create(value="classified", attribute=self.secret_attr, object=self.obj)

    def test_unfiltered_excludes_secret_values(self):
        """allValues without filters should not return values linked to 'Secret' attribute."""
        response = self.query("""
            query {
              allValues {
                edges {
                  node {
                    value
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allValues"]["edges"]
        values = [e["node"]["value"] for e in edges]
        self.assertEqual(values, ["Red"])
        self.assertNotIn("classified", values)

    def test_filtering_by_secret_attribute_returns_nothing(self):
        """Filtering values by attribute name 'Secret' returns nothing (excluded by queryset)."""
        response = self.query("""
            query {
              allValues(filter: { attribute: { name: { exact: "Secret" } } }) {
                edges {
                  node {
                    value
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allValues"]["edges"]
        self.assertEqual(len(edges), 0)

    def test_filtering_by_public_attribute_still_works(self):
        """Filtering by a non-excluded attribute works normally."""
        response = self.query("""
            query {
              allValues(filter: { attribute: { name: { exact: "Color" } } }) {
                edges {
                  node {
                    value
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allValues"]["edges"]
        values = [e["node"]["value"] for e in edges]
        self.assertEqual(values, ["Red"])


class SubEdgeFilterTests(GraphQLTestCase):
    """Tests that tree-structured filter/orderBy/search arguments work on
    sub-edge connections (e.g. values on an Object), not just root-level queries.
    """

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        self.people_type = ObjectType.objects.create(name="People")
        self.email_attr = Attribute.objects.create(
            name="Email", description="Electronic mail", object_type=self.people_type
        )
        self.city_attr = Attribute.objects.create(
            name="City", description="Home city", object_type=self.people_type
        )
        self.phone_attr = Attribute.objects.create(
            name="Phone", description="Phone number", object_type=self.people_type
        )

        self.alice = Object.objects.create(name="Alice", description="Engineer", object_type=self.people_type)
        Value.objects.create(value="alice@example.com", attribute=self.email_attr, object=self.alice)
        Value.objects.create(value="Denver", attribute=self.city_attr, object=self.alice)
        Value.objects.create(value="555-0001", attribute=self.phone_attr, object=self.alice)

    def test_sub_edge_tree_filter(self):
        """Tree-structured filter on a sub-edge connection should work."""
        response = self.query("""
            query {
              allObjects(filter: { name: { exact: "Alice" } }) {
                edges {
                  node {
                    name
                    values(filter: { attribute: { name: { exact: "Email" } } }) {
                      edges {
                        node {
                          value
                        }
                      }
                    }
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), 1)
        values = [e["node"]["value"] for e in edges[0]["node"]["values"]["edges"]]
        self.assertEqual(values, ["alice@example.com"])

    def test_sub_edge_tree_filter_icontains(self):
        """icontains lookup via tree filter on a sub-edge."""
        response = self.query("""
            query {
              allObjects(filter: { name: { exact: "Alice" } }) {
                edges {
                  node {
                    values(filter: { value: { icontains: "example" } }) {
                      edges {
                        node {
                          value
                        }
                      }
                    }
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        values = [
            e["node"]["value"] for e in content["data"]["allObjects"]["edges"][0]["node"]["values"]["edges"]
        ]
        self.assertEqual(values, ["alice@example.com"])

    def test_sub_edge_order_by(self):
        """orderBy on a sub-edge connection should work."""
        response = self.query("""
            query {
              allObjects(filter: { name: { exact: "Alice" } }) {
                edges {
                  node {
                    values(orderBy: [{ value: DESC }]) {
                      edges {
                        node {
                          value
                        }
                      }
                    }
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        values = [
            e["node"]["value"] for e in content["data"]["allObjects"]["edges"][0]["node"]["values"]["edges"]
        ]
        # value field is in ValueOrder.Meta.fields, so ordering should apply
        self.assertEqual(values, sorted(values, reverse=True))

    def test_sub_edge_search(self):
        """search on a sub-edge connection should work."""
        response = self.query("""
            query {
              allObjects(filter: { name: { exact: "Alice" } }) {
                edges {
                  node {
                    values(search: "Denver") {
                      edges {
                        node {
                          value
                        }
                      }
                    }
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        values = [
            e["node"]["value"] for e in content["data"]["allObjects"]["edges"][0]["node"]["values"]["edges"]
        ]
        self.assertEqual(values, ["Denver"])

    def test_sub_edge_unfiltered_returns_all(self):
        """Without filter on sub-edge, all related values should return."""
        response = self.query("""
            query {
              allObjects(filter: { name: { exact: "Alice" } }) {
                edges {
                  node {
                    values {
                      edges {
                        node {
                          value
                        }
                      }
                    }
                  }
                }
              }
            }
            """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        values = [
            e["node"]["value"] for e in content["data"]["allObjects"]["edges"][0]["node"]["values"]["edges"]
        ]
        self.assertEqual(len(values), 3)
