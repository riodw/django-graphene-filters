# ![Graphene Logo](http://graphene-python.org/favicon.png) Django Graphene Filters (Beta)

[![build][build-image]][build-url]
[![pypi][pypi-image]][pypi-url]
<!-- py-coverage:start -->
![coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)
<!-- py-coverage:end -->
![PyPI - License](https://img.shields.io/pypi/l/django-graphene-filters)

[build-image]: https://github.com/riodw/django-graphene-filters/actions/workflows/django.yml/badge.svg
[build-url]: https://github.com/riodw/django-graphene-filters/actions
[pypi-image]: https://img.shields.io/pypi/v/django-graphene-filters.svg?style=flat
[pypi-url]: https://pypi.org/project/django-graphene-filters/


This package contains Advanced auto related filters for [graphene-django](https://github.com/graphql-python/graphene-django).


#### This package takes inspiration from:
- https://pypi.org/project/graphene-django-filter/
- https://pypi.org/project/djangorestframework-filters


## Installation

```shell
# pip
pip install django-graphene-filters
# poetry
poetry add django-graphene-filters
# uv
uv add django-graphene-filters
```

## Build

```shell
poetry update
poetry lock
poetry build
```

## Publish

```shell
poetry publish --username __token__ --password PASSWORD
```

## Testing
```shell
poetry run coverage run -m pytest
poetry run coverage report --fail-under=100
poetry run coverage report --show-missing

poetry run coverage run -m pytest tests/test_input_data_factories.py && poetry run coverage report -m django_graphene_filters/input_data_factories.py
# Run Full Test Pipeline
https://github.com/riodw/django-graphene-filters/actions/workflows/django.yml
```

## Running 
```shell
poetry run python examples/cookbook/manage.py runserver
```


### Local usage

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

### Updating:

- poetry show --outdated

```shell
poetry show --outdated
poetry show -o
poetry add --dev
poetry env remove 3.11
```

### Formatting and Linting:
```shell
# pyproject.toml [tool.black]
poetry run black .
# pyproject.toml [tool.ruff]
poetry run ruff check --fix .
```

### Updating Version:
- pyproject.toml:4
- django_graphene_filters/__init__.py:18
- tests/test_django_graphene_filters.py:8

## Notes:

Files to do:

- filterset.py `AdvancedFilterSet`
- input_data_factories.py
