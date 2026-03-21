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

Now head on over to
[http://127.0.0.1:8000/graphql](http://127.0.0.1:8000/graphql)
and run some queries!
(See the [Graphene-Django Tutorial](http://docs.graphene-python.org/projects/django/en/latest/tutorial-relay/#testing-our-graphql-schema)
for some example queries)
