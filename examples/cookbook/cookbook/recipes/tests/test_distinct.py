"""Integration tests for DISTINCT ON via ASC_DISTINCT / DESC_DISTINCT in orderBy."""

import json

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from django.contrib.auth import get_user_model
from graphene_django.utils import GraphQLTestCase

User = get_user_model()


class DistinctOnTests(GraphQLTestCase):
    """Tests that ASC_DISTINCT / DESC_DISTINCT in orderBy produces one row per partition."""

    GRAPHQL_URL = "/graphql/"

    def setUp(self):
        super().setUp()
        self.staff_user = User.objects.create_user(username="staff", password="testpass", is_staff=True)
        self.client.login(username="staff", password="testpass")

        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

        # Create 3 ObjectTypes with multiple Objects each
        self.type_a = ObjectType.objects.create(name="alpha", description="First")
        self.type_b = ObjectType.objects.create(name="beta", description="Second")
        self.type_c = ObjectType.objects.create(name="gamma", description="Third")

        # alpha: 3 objects
        Object.objects.create(name="a1", object_type=self.type_a, is_private=False)
        Object.objects.create(name="a2", object_type=self.type_a, is_private=True)
        Object.objects.create(name="a3", object_type=self.type_a, is_private=False)

        # beta: 2 objects
        Object.objects.create(name="b1", object_type=self.type_b, is_private=False)
        Object.objects.create(name="b2", object_type=self.type_b, is_private=False)

        # gamma: 1 object
        Object.objects.create(name="g1", object_type=self.type_c, is_private=True)

    def test_distinct_on_object_type(self):
        """One Object per ObjectType, alphabetical by type name."""
        response = self.query("""
            query {
              allObjects(orderBy: [
                { objectType: { name: ASC_DISTINCT } },
                { name: ASC }
              ]) {
                edges { node { name objectType { name } } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]

        # 3 ObjectTypes → 3 rows
        self.assertEqual(len(edges), 3)
        names = [e["node"]["name"] for e in edges]
        types = [e["node"]["objectType"]["name"] for e in edges]

        # Each type appears exactly once
        self.assertEqual(sorted(types), ["alpha", "beta", "gamma"])
        # Within each partition, the first alphabetically by name is kept
        self.assertEqual(names[types.index("alpha")], "a1")
        self.assertEqual(names[types.index("beta")], "b1")
        self.assertEqual(names[types.index("gamma")], "g1")

    def test_desc_distinct_keeps_last(self):
        """DESC_DISTINCT keeps the last row per partition (by name descending)."""
        response = self.query("""
            query {
              allObjects(orderBy: [
                { objectType: { name: DESC_DISTINCT } },
                { name: DESC }
              ]) {
                edges { node { name objectType { name } } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]

        self.assertEqual(len(edges), 3)
        names = [e["node"]["name"] for e in edges]
        types = [e["node"]["objectType"]["name"] for e in edges]

        # DESC on name means the last alphabetically is kept
        self.assertEqual(names[types.index("alpha")], "a3")
        self.assertEqual(names[types.index("beta")], "b2")

    def test_distinct_on_boolean_field(self):
        """Distinct on is_private → at most 2 rows (true/false)."""
        response = self.query("""
            query {
              allObjects(orderBy: [
                { isPrivate: ASC_DISTINCT },
                { name: ASC }
              ]) {
                edges { node { name isPrivate } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]

        # We have both private and non-private objects → exactly 2 rows
        self.assertEqual(len(edges), 2)
        private_values = {e["node"]["isPrivate"] for e in edges}
        self.assertEqual(private_values, {True, False})

    def test_distinct_with_filter(self):
        """Filter + distinct combined: filter narrows first, then distinct deduplicates."""
        response = self.query("""
            query {
              allObjects(
                filter: { name: { icontains: "a" } }
                orderBy: [
                  { objectType: { name: ASC_DISTINCT } },
                  { name: ASC }
                ]
              ) {
                edges { node { name objectType { name } } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        types = [e["node"]["objectType"]["name"] for e in edges]

        # Only alpha objects contain "a" (a1, a2, a3) → one distinct type
        self.assertEqual(len(edges), 1)
        self.assertEqual(types, ["alpha"])

    def test_distinct_with_pagination(self):
        """Distinct + first/after pagination."""
        response = self.query("""
            query {
              allObjects(
                first: 2
                orderBy: [
                  { objectType: { name: ASC_DISTINCT } },
                  { name: ASC }
                ]
              ) {
                edges { node { name objectType { name } } }
                pageInfo { hasNextPage endCursor }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        data = content["data"]["allObjects"]
        edges = data["edges"]

        # 3 distinct rows, first: 2 → 2 rows, hasNextPage=True
        self.assertEqual(len(edges), 2)
        self.assertTrue(data["pageInfo"]["hasNextPage"])

        # Fetch the next page
        cursor = data["pageInfo"]["endCursor"]
        response2 = self.query(
            """
            query($cursor: String) {
              allObjects(
                first: 2
                after: $cursor
                orderBy: [
                  { objectType: { name: ASC_DISTINCT } },
                  { name: ASC }
                ]
              ) {
                edges { node { name objectType { name } } }
                pageInfo { hasNextPage }
              }
            }
        """,
            variables=json.dumps({"cursor": cursor}),
        )
        self.assertResponseNoErrors(response2)
        content2 = json.loads(response2.content)
        edges2 = content2["data"]["allObjects"]["edges"]

        # 1 remaining row
        self.assertEqual(len(edges2), 1)
        self.assertFalse(content2["data"]["allObjects"]["pageInfo"]["hasNextPage"])

    def test_no_distinct_returns_all(self):
        """Standard ASC/DESC without _DISTINCT returns all rows (regression check)."""
        response = self.query("""
            query {
              allObjects(orderBy: [{ name: ASC }]) {
                edges { node { name } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]

        # All 6 objects returned
        self.assertEqual(len(edges), 6)

    def test_distinct_count_matches_unique_values(self):
        """Number of distinct rows = number of unique ObjectTypes in the DB."""
        unique_type_count = ObjectType.objects.count()
        response = self.query("""
            query {
              allObjects(orderBy: [
                { objectType: { name: ASC_DISTINCT } },
                { name: ASC }
              ]) {
                edges { node { objectType { name } } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), unique_type_count)

    def test_distinct_on_flat_field_name(self):
        """Distinct on the name field — each unique name gets one row."""
        # All names are unique in setUp → distinct on name returns all
        response = self.query("""
            query {
              allObjects(orderBy: [{ name: ASC_DISTINCT }]) {
                edges { node { name } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), 6)

        # Now create a duplicate name
        Object.objects.create(name="a1", object_type=self.type_b, is_private=False)
        response2 = self.query("""
            query {
              allObjects(orderBy: [{ name: ASC_DISTINCT }]) {
                edges { node { name } }
              }
            }
        """)
        self.assertResponseNoErrors(response2)
        content2 = json.loads(response2.content)
        edges2 = content2["data"]["allObjects"]["edges"]
        # 7 objects but 6 unique names → 6 rows
        self.assertEqual(len(edges2), 6)

    def test_distinct_filter_eliminates_entire_group(self):
        """When a filter removes all objects in a group, that group doesn't appear."""
        response = self.query("""
            query {
              allObjects(
                filter: { name: { icontains: "b" } }
                orderBy: [
                  { objectType: { name: ASC_DISTINCT } },
                  { name: ASC }
                ]
              ) {
                edges { node { name objectType { name } } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        types = [e["node"]["objectType"]["name"] for e in edges]
        # Only beta objects contain "b" (b1, b2) → alpha and gamma eliminated
        self.assertNotIn("alpha", types)
        self.assertNotIn("gamma", types)
        self.assertIn("beta", types)
        self.assertEqual(len(edges), 1)

    def test_distinct_empty_result(self):
        """Distinct on an empty filtered result returns 0 rows."""
        response = self.query("""
            query {
              allObjects(
                filter: { name: { exact: "DOES_NOT_EXIST" } }
                orderBy: [
                  { objectType: { name: ASC_DISTINCT } }
                ]
              ) {
                edges { node { name } }
              }
            }
        """)
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        edges = content["data"]["allObjects"]["edges"]
        self.assertEqual(len(edges), 0)
