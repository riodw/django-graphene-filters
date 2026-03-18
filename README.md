# ![Graphene Logo](http://graphene-python.org/favicon.png) Django Graphene Filters (Beta)

[![build][build-image]][build-url] [![pypi][pypi-image]][pypi-url] [![coveralls][coveralls-image]][coveralls-url] [![license][license-image]][license-url] [![changelog][changelog-image]][changelog-url]

[build-image]: https://github.com/riodw/django-graphene-filters/actions/workflows/django.yml/badge.svg
[build-url]: https://github.com/riodw/django-graphene-filters/actions
[pypi-image]: https://img.shields.io/pypi/v/django-graphene-filters.svg?style=flat
[pypi-url]: https://pypi.org/project/django-graphene-filters/
[coveralls-image]: https://coveralls.io/repos/github/riodw/django-graphene-filters/badge.svg?branch=master
[coveralls-url]: https://coveralls.io/github/riodw/django-graphene-filters?branch=master
[license-image]: https://img.shields.io/pypi/l/django-graphene-filters
[license-url]: https://github.com/riodw/django-graphene-filters/blob/master/LICENSE
[changelog-image]: https://img.shields.io/badge/changelog-CHANGELOG.md-blue
[changelog-url]: https://github.com/riodw/django-graphene-filters/blob/master/CHANGELOG.md

This package contains Advanced auto related filters for [graphene-django](https://github.com/graphql-python/graphene-django).

#### This package takes inspiration from:

- https://pypi.org/project/graphene-django-filter
- https://pypi.org/project/djangorestframework-filters


## Installation

```shell
# pip
pip install django-graphene-filters
# uv
uv add django-graphene-filters
```

## Development Setup

```shell
# Install uv (if not already installed)
# https://docs.astral.sh/uv/getting-started/installation/

# Clone and install
git clone https://github.com/riodw/django-graphene-filters.git
cd django-graphene-filters
uv sync
```

## Running

```shell
uv run python examples/cookbook/manage.py runserver
```

## Testing

```shell
uv run coverage run -m pytest
uv run coverage report --fail-under=100
uv run coverage report --show-missing

uv run coverage run -m pytest tests/test_input_data_factories.py && uv run coverage report -m django_graphene_filters/input_data_factories.py
# Run Full Test Pipeline
https://github.com/riodw/django-graphene-filters/actions/workflows/django.yml
```

### Formatting and Linting:

```shell
# pyproject.toml [tool.black]
uv run black .
# pyproject.toml [tool.ruff]
uv run ruff check --fix .
```

## Build

```shell
uv lock
uv build
```

### Updating Version:

- pyproject.toml:4
- django_graphene_filters/**init**.py:21
- tests/test_django_graphene_filters.py:8

## Publish

```shell
uv publish --token PASSWORD
```

### Updating:

```shell
# Show outdated packages
uv pip list --outdated

# Add a dev dependency
uv add --group dev <package>

# Remove the virtual environment
rm -rf .venv
```

### Local usage

1. go to the project you want to install the package
2. add `django-graphene-filters` to your `pyproject.toml` dependencies
3. point it at your local checkout:

```toml
# In your project's pyproject.toml
[tool.uv.sources]
django-graphene-filters = { path = "../django-graphene-filters", editable = true }
```

Then run:

```shell
uv sync
```

## Notes:

Files to do:

- filterset.py `AdvancedFilterSet`
- input_data_factories.py
