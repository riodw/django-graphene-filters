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

You can quickly populate the database with random "People" objects (including Email, Phone, and City attributes) using the custom management command:

```bash
# Create 50 people (default)
uv run python manage.py create_people

# Create a specific number of people
uv run python manage.py create_people 100
```

You can also populate through `/admin`
- http://127.0.0.1:8000/admin/recipes/object/?create_people=50

Now head on over to
[http://127.0.0.1:8000/graphql](http://127.0.0.1:8000/graphql)
and run some queries!
(See the [Graphene-Django Tutorial](http://docs.graphene-python.org/projects/django/en/latest/tutorial-relay/#testing-our-graphql-schema)
for some example queries)
