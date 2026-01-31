# Django Graphene Filters
- https://pypi.org/project/graphene-django-filter/
- https://pypi.org/project/djangorestframework-filters

This package contains Advanced auto related filters for [graphene-django](https://github.com/graphql-python/graphene-django).

# Installation

```shell
# pip
pip install django-graphene-filters
# poetry
poetry add django-graphene-filters
```

# Build

```shell
poetry update
poetry build
```

# Publish

```shell
poetry publish --username __token__ --password PASSWORD
```

# Testing
```shell
poetry run coverage run -m pytest
poetry run coverage report --fail-under=100
```

# Running 
```shell
poetry run python examples/cookbook/manage.py runserver
```


## Local usage

1. go to the project you want to install the package
2. run `pipenv shell`
3. run `pip install -e .`
EXAMPLE:
```
cd ~/projects/django-graphene-filters
pipenv install -e .
cd ~/projects/doormatkey.django/doormatkey
pipenv lock
```

## Updating:

- poetry upgradeable packages

```shell
poetry show -o
poetry add --dev
poetry show --outdated
poetry lock
poetry env remove 3.11
poetry run flake8 .
poetry run black .
```

## Updating Version:
- pyproject.toml:4
- django_graphene_filters/__init__.py:18
- tests/test_django_graphene_filters.py:8

# Notes:

Files to do:

- filterset.py `AdvancedFilterSet`
- input_data_factories.py
