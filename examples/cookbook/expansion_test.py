import pprint
from cookbook.recipes.schema import ObjectFilter  # Adjust import based on your app structure

print("--- DIAGNOSTIC START ---")

# 1. Check if the RelatedFilter is detected
print(f"Related Filters detected: {list(ObjectFilter.related_filters.keys())}")

# 2. Check the Target FilterSet
rf = ObjectFilter.related_filters['object_type']
print(f"Target FilterSet: {rf.filterset}")
print(f"Target Base Filters: {list(rf.filterset.base_filters.keys())}")

# 3. CRITICAL: Check what get_filters() returns
# This triggers the expansion logic
all_filters = ObjectFilter.get_filters()
keys = list(all_filters.keys())

print(f"\nTotal Filters count: {len(keys)}")
print("Filters details:")
for k, v in all_filters.items():
    print(f"Key: {k}, field_name: {v.field_name}, lookup_expr: {v.lookup_expr}")

# 4. Check if expansion happened
if "object_type__description__icontains" in all_filters:
    print("\n[SUCCESS] Expansion Logic is working in filterset.py")
else:
    print("\n[FAILURE] Expansion Logic is BROKEN. Keys are missing.")

print("--- DIAGNOSTIC END ---")
