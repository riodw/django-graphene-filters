from django.db import models
from django.db.models.expressions import Expression
from django.db.models.lookups import Lookup, Transform

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
    # Bare transform is included (implicit __exact shorthand)
    assert "mock" in lookups
    # Expanded sub-lookups are also included (e.g. 'mock__exact')
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


def test_lookups_for_transform_multi_cycle_prevention():
    """Cycles across multiple transform classes terminate.

    `a__b__a__b__…` would previously recurse forever — the direct self-loop
    guard only caught `a__a`. The visited-class set now breaks this chain
    when any transform type reappears.
    """

    class TransformA(Transform):
        lookup_name = "cycle_a"

        @property
        def output_field(self):
            f = models.CharField()
            # Forward reference — TransformB is in the enclosing scope by the
            # time this property actually runs.
            f.register_lookup(TransformB)
            return f

    class TransformB(Transform):
        lookup_name = "cycle_b"

        @property
        def output_field(self):
            f = models.CharField()
            f.register_lookup(TransformA)  # closes the cycle
            return f

    transform = TransformA(Expression(models.CharField()))
    # Without multi-cycle detection this would recurse A → B → A → B → …
    # until RecursionError. With detection, it terminates.
    lookups = lookups_for_transform(transform)
    # Bare sub-transform B is emitted before recursing into it.
    assert "cycle_b" in lookups
    # Expanded B lookups from its output field are included (e.g. cycle_b__exact).
    assert any(lookup.startswith("cycle_b__") for lookup in lookups)


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
    # Bare sub-transform is included (implicit __exact shorthand)
    assert "sub" in lookups
    # Expanded sub-lookups are also included (e.g. 'sub__exact')
    assert any(lookup.startswith("sub__") for lookup in lookups)


def test_lookups_for_transform_own_lookups():
    """Lookups registered directly on a Transform class are discovered."""

    class OwnLookup(Lookup):
        lookup_name = "own"

        def as_sql(self, compiler, connection):
            return "", []

    class TransformWithOwnLookup(Transform):
        lookup_name = "towl"

        @property
        def output_field(self):
            return models.CharField()

    TransformWithOwnLookup.register_lookup(OwnLookup)

    transform = TransformWithOwnLookup(Expression(models.CharField()))
    lookups = lookups_for_transform(transform)
    # OwnLookup is registered on the transform itself, not on output_field
    assert "own" in lookups
    # Standard output_field lookups are still included
    assert "exact" in lookups
