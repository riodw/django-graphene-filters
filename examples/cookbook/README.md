Cookbook Example (Relay) Django Project
===============================

This example project demos integration between Graphene and Django.
The project contains two apps, one named `ingredients` and another
named `recipes`.

Getting started
---------------

First you'll need to get the source of the project. Do this by cloning the
whole Graphene repository:

```bash
# Get the example project code
git clone https://github.com/graphql-python/graphene-django.git
cd graphene-django/examples/cookbook
```

It is good idea (but not required) to create a virtual environment
for this project. We'll do this using
[virtualenv](http://docs.python-guide.org/en/latest/dev/virtualenvs/)
to keep things simple,
but you may also find something like
[virtualenvwrapper](https://virtualenvwrapper.readthedocs.org/en/latest/)
to be useful:

```bash
# Create a virtualenv in which we can install the dependencies
virtualenv env
source env/bin/activate
```

Now we can install our dependencies:

```bash
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

Generate Dummy Data
-------------------

You can quickly populate the database with random "People" objects (including Email, Phone, and City attributes) using the custom management command:

```bash
# Create 50 people (default)
./manage.py create_people

# Create a specific number of people
./manage.py create_people 100
```

Now you should be ready to start the server:

```bash
./manage.py runserver
```

Now head on over to
[http://127.0.0.1:8000/graphql](http://127.0.0.1:8000/graphql)
and run some queries!
(See the [Graphene-Django Tutorial](http://docs.graphene-python.org/projects/django/en/latest/tutorial-relay/#testing-our-graphql-schema)
for some example queries)
