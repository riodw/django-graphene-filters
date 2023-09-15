# Django Graphene Filters

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

## Local testing

1. run `pipenv shell`
2. go to the project you want to install the package
3. run `pip install -e .`

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

# Notes:

Files to do:

- filterset.py `AdvancedFilterSet`
- input_data_factories.py
