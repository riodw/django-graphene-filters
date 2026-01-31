Cookbook Example (Relay) Django Project
===============================


# Testing

```shell
./manage.py test cookbook.recipes -v 2

# Or for even more detail (including database creation steps):
./manage.py test cookbook.recipes -v 3
```

# Setup

```bash
# Create a virtualenv in which we can install the dependencies
virtualenv env
source env/bin/activate

pip install -r requirements.txt
```

Now setup our database:

```bash
# Setup the database
./manage.py migrate

# Create an admin user (useful for logging into the admin UI
# at http://127.0.0.1:8000/admin)
./manage.py createsuperuser
```

Now you should be ready to start the server:

```bash
./manage.py runserver
```

Generate Dummy Data
-------------------

You can quickly populate the database with random "People" objects (including Email, Phone, and City attributes) using the custom management command:

```bash
# Create 50 people (default)
./manage.py create_people

# Create a specific number of people
./manage.py create_people 100
```

You can also populate through `/admin`
- http://127.0.0.1:8000/admin/recipes/object/?create_people=50

Now head on over to
[http://127.0.0.1:8000/graphql](http://127.0.0.1:8000/graphql)
and run some queries!
(See the [Graphene-Django Tutorial](http://docs.graphene-python.org/projects/django/en/latest/tutorial-relay/#testing-our-graphql-schema)
for some example queries)
