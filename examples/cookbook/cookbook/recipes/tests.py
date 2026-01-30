from django.test import TestCase
from cookbook.recipes.models import Object
from cookbook.recipes.services import create_people

def ensure_people_count(x: int):
    """
    Ensures at least X objects with object_type "People" exist.
    Creates only the difference if some already exist.
    """
    current_count = Object.objects.filter(object_type__name="People").count()
    if current_count < x:
        create_people(x - current_count)

class PeopleServiceTests(TestCase):
    def test_ensure_three_people(self):
        # Initial state should be 0
        ensure_people_count(3)
        count = Object.objects.filter(object_type__name="People").count()
        self.assertEqual(count, 3, f"Expected 3 people, found {count}")

    def test_ensure_four_people(self):
        # Each test in TestCase starts with a clean database (in a transaction)
        # So we test that we get exactly 4 when we ask for 4
        ensure_people_count(4)
        count = Object.objects.filter(object_type__name="People").count()
        self.assertEqual(count, 4, f"Expected 4 people, found {count}")
    
    def test_incremental_behavior(self):
        """
        Explicitly test the logic where it only creates the difference.
        """
        # 1. Create 2 people
        ensure_people_count(2)
        self.assertEqual(Object.objects.filter(object_type__name="People").count(), 2)
        
        # 2. Ask for 5 people total (should create 3 more)
        ensure_people_count(5)
        self.assertEqual(Object.objects.filter(object_type__name="People").count(), 5)
        
        # 3. Ask for 5 again (should create 0)
        ensure_people_count(5)
        self.assertEqual(Object.objects.filter(object_type__name="People").count(), 5)


from graphene_django.utils import GraphQLTestCase
import json

class PeopleGraphQLTests(GraphQLTestCase):
    def query_people_count(self):
        response = self.query(
            '''
            query {
              allObjects(objectType_Name: "People") {
                edges {
                  node {
                    id
                  }
                }
              }
            }
            '''
        )
        content = json.loads(response.content)
        # Verify no errors in response
        if 'errors' in content:
            raise Exception(f"GraphQL Errors: {content['errors']}")
            
        return len(content['data']['allObjects']['edges'])

    def test_graphql_three_people(self):
        ensure_people_count(3)
        count = self.query_people_count()
        self.assertEqual(count, 3, f"Expected 3 people via GraphQL, found {count}")

    def test_graphql_four_people(self):
        ensure_people_count(4)
        count = self.query_people_count()
        self.assertEqual(count, 4, f"Expected 4 people via GraphQL, found {count}")

    def test_graphql_person_values_count(self):
        """
        Verify that each person has exactly 3 values through GraphQL
        and that they share the same 3 unique attributes.
        """
        ensure_people_count(2)
        response = self.query(
            '''
            query {
              allObjects(objectType_Name: "People") {
                edges {
                  node {
                    name
                    valueSet {
                      edges {
                        node {
                          value
                          attribute {
                            id
                            name
                          }
                        }
                      }
                    }
                  }
                }
              }
            }
            '''
        )
        self.assertResponseNoErrors(response)
        content = json.loads(response.content)
        
        edges = content['data']['allObjects']['edges']
        self.assertEqual(len(edges), 2)
        
        all_attribute_ids = set()
        
        for edge in edges:
            node = edge['node']
            values = node['valueSet']['edges']
            self.assertEqual(len(values), 3, f"Person {node['name']} should have 3 values, but has {len(values)}")
            
            attr_names = []
            for v in values:
                attr = v['node']['attribute']
                attr_names.append(attr['name'])
                all_attribute_ids.add(attr['id'])
            
            self.assertIn("Email", attr_names)
            self.assertIn("Phone", attr_names)
            self.assertIn("City", attr_names)

        # Verify that across all people, only 3 unique Attribute IDs were used
        self.assertEqual(
            len(all_attribute_ids), 
            3, 
            f"Expected exactly 3 unique attribute IDs, but found {len(all_attribute_ids)}: {all_attribute_ids}"
        )
