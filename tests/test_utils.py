from django.db import models
from django.db.models.expressions import Expression
from django.db.models.lookups import Transform

from django_graphene_filters.utils import lookups_for_field, lookups_for_transform


class MockTransform(Transform):
    lookup_name = "mock"


def test_lookups_for_field_no_transform():
    field = models.CharField()
    lookups = lookups_for_field(field)
    assert "exact" in lookups
    assert "icontains" in lookups


class MockField(models.CharField):
    pass


def test_lookups_for_field_with_transform():
    # Register transform on the custom field class
    MockField.register_lookup(MockTransform)

    field = MockField()
    lookups = lookups_for_field(field)
    # Transforms yield nested lookups like 'mock__exact'
    assert any(lookup.startswith("mock__") for lookup in lookups)


class NestedTransform(Transform):
    lookup_name = "nested"

    @property
    def output_field(self):
        return models.CharField()


def test_lookups_for_transform():
    # We need a transform that has lookups on its output_field
    transform = NestedTransform(Expression(models.CharField()))
    lookups = lookups_for_transform(transform)
    assert "exact" in lookups
    assert "icontains" in lookups


def test_lookups_for_transform_recursion_prevention():
    class RecursiveTransform(Transform):
        lookup_name = "recursive"

        @property
        def output_field(self):
            f = models.CharField()
            f.register_lookup(RecursiveTransform)
            return f

    transform = RecursiveTransform(Expression(models.CharField()))
    lookups = lookups_for_transform(transform)
    # It should not infinite loop
    assert "exact" in lookups


def test_lookups_for_nested_transform():
    class SubTransform(Transform):
        lookup_name = "sub"

    class ParentTransform(Transform):
        lookup_name = "parent"

        @property
        def output_field(self):
            f = models.CharField()
            f.register_lookup(SubTransform)
            return f

    transform = ParentTransform(Expression(models.CharField()))
    lookups = lookups_for_transform(transform)
    # parent__sub__exact etc.
    assert any(lookup.startswith("sub__") for lookup in lookups)
