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
uv sync --upgrade
```

## Running

```shell
uv run python examples/cookbook/manage.py runserver
```

### Seeding the example database

The cookbook example dynamically discovers **all** Faker providers at runtime and seeds
the database accordingly. The command is idempotent — it ensures at least N objects exist
per provider and only creates the shortfall.

```shell
# Ensure 5 objects per provider (default)
uv run python examples/cookbook/manage.py seed_data

# Ensure 50 objects per provider
uv run python examples/cookbook/manage.py seed_data 50

# Delete the first 10 objects (and their cascading values)
uv run python examples/cookbook/manage.py delete_data 10

# Delete all objects and values
uv run python examples/cookbook/manage.py delete_data all

# Wipe all four tables
uv run python examples/cookbook/manage.py delete_data everything
```

### Test users

Create test users with individual Django `view_*` permissions for exercising
`get_queryset` permission branches. Each set creates 6 users: 1 staff,
1 regular (no perms), and 4 per-model permission users. All share password
`admin`. Superusers are never deleted.

```shell
# Create 1 set of test users (6 users)
uv run python examples/cookbook/manage.py create_users

# Create 3 sets (18 users)
uv run python examples/cookbook/manage.py create_users 3

# Delete all non-superusers
uv run python examples/cookbook/manage.py delete_users all

# Delete the first 5 non-superusers
uv run python examples/cookbook/manage.py delete_users 5
```

## Testing

```shell
uv run coverage run -m pytest
uv run coverage report --fail-under=100
uv run coverage report --show-missing
# run on a single test file
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

- `pyproject.toml:4`
- `django_graphene_filters/__init__.py:22`
- `tests/test_django_graphene_filters.py:8`

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

## Permissions & Cascade Visibility

When a node's `get_queryset` hides rows (e.g. `is_private=False` for non-staff),
FK fields pointing to hidden targets would normally cause
`"Cannot return null for non-nullable field"` errors.

`AdvancedDjangoObjectType` solves this with **sentinel nodes** — redacted
instances (`pk=0`) returned by `get_node` when the real row is hidden.
Every node exposes an `isRedacted: Boolean!` field so clients can detect them.

Use `apply_cascade_permissions` inside `get_queryset` to proactively exclude
rows whose FK targets are hidden:

```python
from django_graphene_filters import AdvancedDjangoObjectType, apply_cascade_permissions

class ObjectNode(AdvancedDjangoObjectType):
    class Meta:
        model = Object
        interfaces = (Node,)
        fields = "__all__"

    @classmethod
    def get_queryset(cls, queryset, info):
        user = getattr(info.context, "user", None)
        if user and user.is_staff:
            return queryset
        return apply_cascade_permissions(cls, queryset.filter(is_private=False), info)
```

See the [CHANGELOG](CHANGELOG.md) for full details on the 0.4.0 permissions system.
