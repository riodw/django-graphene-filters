Cookbook Example (Relay) Django Project
===============================


# Testing

```shell
./manage.py test cookbook.recipes -v 2

# Or for even more detail (including database creation steps):
./manage.py test cookbook.recipes -v 3

uv run python manage.py shell -c "exec(open('check_no_flat_filters_test.py').read())"
uv run python manage.py shell -c "exec(open('diagnostic_trees_test.py').read())"
uv run python manage.py shell -c "exec(open('expansion_test.py').read())"
uv run python manage.py shell -c "exec(open('schema_arguments_test.py').read())"
```

# Setup

```bash
cd examples/cookbook
source .venv/bin/activate

# Install dependencies (uses the pyproject.toml in this directory,
# which references the parent package via editable install)
uv sync
```

Now setup our database:

```bash
# Setup the database
uv run python manage.py makemigrations
uv run python manage.py migrate

# Create an admin user (useful for logging into the admin UI
# at http://127.0.0.1:8000/admin)
uv run python manage.py createsuperuser
```

Now you should be ready to start the server:

```bash
uv run python manage.py runserver
```

Generate Dummy Data
-------------------

The `seed_data` management command dynamically discovers **all** Faker providers at runtime
and seeds the database with one `ObjectType` per provider, one `Attribute` per generator method,
and N `Object` instances (each with a `Value` for every attribute).

The command is idempotent — it ensures at least N objects exist per provider and only creates the shortfall.

```bash
# Ensure 5 objects per provider (default)
uv run python manage.py seed_data

# Ensure a specific number per provider
uv run python manage.py seed_data 50
```

You can also populate through `/admin`
- http://127.0.0.1:8000/admin/recipes/object/?seed_data=50

Delete Data
-----------

The `delete_data` management command removes data from the database.

```bash
# Delete the first 10 objects (and their cascading values)
uv run python manage.py delete_data 10

# Delete ALL objects and values
uv run python manage.py delete_data all

# Wipe all four tables (Value, Object, Attribute, ObjectType)
uv run python manage.py delete_data everything
```

You can also delete through `/admin`
- http://127.0.0.1:8000/admin/recipes/object/?delete_data=10
- http://127.0.0.1:8000/admin/recipes/object/?delete_data=all
- http://127.0.0.1:8000/admin/recipes/object/?delete_data=everything

Test Users
----------

Create test users with individual Django `view_*` permissions for exercising
`get_queryset` permission branches. Each set creates 6 users:

- `staff_N` — `is_staff=True`
- `regular_N` — no permissions, not staff
- `view_objecttype_N` — has `recipes.view_objecttype`
- `view_object_N` — has `recipes.view_object`
- `view_attribute_N` — has `recipes.view_attribute`
- `view_value_N` — has `recipes.view_value`

All share the password `admin`.

```bash
# Create 1 set of test users (6 users, default)
uv run python manage.py create_users

# Create 3 sets (18 users)
uv run python manage.py create_users 3

# Delete all non-superusers
uv run python manage.py delete_users all

# Delete the first 5 non-superusers
uv run python manage.py delete_users 5
```

You can also manage test users through `/admin`:
- http://127.0.0.1:8000/admin/auth/user/?create_users=1
- http://127.0.0.1:8000/admin/auth/user/?delete_users=all

Now head on over to
[http://*********:8000/graphql](http://*********:8000/graphql)
and run some queries!
(See the [Graphene-Django Tutorial](http://docs.graphene-python.org/projects/django/en/latest/tutorial-relay/#testing-our-graphql-schema)
for some example queries)
