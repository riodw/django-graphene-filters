import pprint
from cookbook.recipes.schema import Query
from django_graphene_filters import AdvancedDjangoFilterConnectionField

print("--- SCHEMA ARGUMENTS DIAGNOSTIC START ---")

# The Query class has an 'all_objects' field which is an AdvancedDjangoFilterConnectionField
field = Query.all_objects
if not isinstance(field, AdvancedDjangoFilterConnectionField):
    # Depending on Graphene version/initialization, it might be wrapped or already resolved
    print(f"Warning: Query.all_objects is {type(field)}, not AdvancedDjangoFilterConnectionField")

# Access the filtering_args
# In Graphene, fields often need to be 'resolved' or accessed in a way that triggers argument generation
args = field.filtering_args

print(f"Total arguments found: {len(args)}")
print("Arguments list:")
for arg_name in sorted(args.keys()):
    print(f"  - {arg_name}")

# The user mentioned 'objectType_Name_Contains' (or similar camelCase)
# However, the keys in filtering_args are usually snake_case before Graphene converts them.
# We want to find any argument that represents a path (contains __) and belongs to a relation.

flat_relation_args = [a for a in args.keys() if "__" in a and any(rel in a for rel in ["object_type", "values"])]

if len(flat_relation_args) > 0:
    print("\n[FAILURE] Found flat arguments for related fields in the schema:")
    for a in sorted(flat_relation_args):
        print(f"  - {a}")
else:
    print("\n[SUCCESS] No flat related arguments found (excluding nested 'filter').")

# Specifically check for the 'filter' argument
if "filter" in args:
    print("\n[SUCCESS] 'filter' argument exists.")
else:
    print("\n[FAILURE] 'filter' argument is MISSING.")

print("--- SCHEMA ARGUMENTS DIAGNOSTIC END ---")
