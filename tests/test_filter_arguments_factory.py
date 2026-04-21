import warnings
from unittest.mock import MagicMock, patch

import graphene
import pytest
from django.db import models

from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory
from django_graphene_filters.filterset import AdvancedFilterSet


class FactModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "recipes"


class FactFilterSet(AdvancedFilterSet):
    class Meta:
        model = FactModel
        fields = ["name"]


def test_factory_special_filter():
    # We want to trigger line 148: if root.name in self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES:
    # Roots come from filterset_to_trees.
    # We need a filter where field_name starts with a special postfix.
    from django_graphene_filters.filters import SearchQueryFilter

    class SpecialFS(AdvancedFilterSet):
        search = SearchQueryFilter()

        class Meta:
            model = FactModel
            fields = []

    factory = FilterArgumentsFactory(SpecialFS, "Special")
    args = factory.arguments
    assert "filter" in args


def test_create_input_object_type_cache():
    # Call twice to hit line 188
    FilterArgumentsFactory.input_object_types = {}  # Reset
    t1 = FilterArgumentsFactory.create_input_object_type("CachedType", {"f": graphene.String()})
    t2 = FilterArgumentsFactory.create_input_object_type("CachedType", {"f": graphene.String()})
    assert t1 is t2


def test_class_name_collision_raises_type_error():
    """Two distinct FilterSet classes with the same ``__name__`` must raise on registration.

    Under class-based naming (``docs/spec-base_type_naming.md``) the caller can no
    longer choose a prefix, so the old "same-prefix-different-class" warn scenario
    disappears.  What remains — and must stay loud — is the case where two distinct
    classes in different modules happen to share a Python ``__name__`` (e.g.
    ``app_a.filters.BrandFilter`` vs ``app_b.filters.BrandFilter``).  The spec
    mandates a strict ``TypeError`` on the second registration attempt: class-based
    naming turns this from "user input issue" into "bug".  See spec
    §"Class-name collision handling".
    """

    class AltModel(models.Model):
        title = models.CharField(max_length=100)

        class Meta:
            app_label = "recipes"

    # Build two DISTINCT classes that both report ``__name__ == "CollidingBrandFilter"``.
    # ``type(...)`` lets us fabricate the collision that real users hit when two
    # modules happen to declare FilterSets with the same short class name.
    first = type(
        "CollidingBrandFilter",
        (AdvancedFilterSet,),
        {"Meta": type("Meta", (), {"model": FactModel, "fields": ["name"]})},
    )
    second = type(
        "CollidingBrandFilter",
        (AdvancedFilterSet,),
        {"Meta": type("Meta", (), {"model": AltModel, "fields": ["title"]})},
    )
    assert first.__name__ == second.__name__ == "CollidingBrandFilter"
    assert first is not second

    type_name = first.type_name_for()
    FilterArgumentsFactory.input_object_types.pop(type_name, None)
    FilterArgumentsFactory._type_filterset_registry.pop(type_name, None)

    try:
        # First registration succeeds and populates the caches.
        FilterArgumentsFactory(first).arguments

        # Second registration with a *different* class claiming the same type name
        # must raise — this is the spec-mandated strict behaviour.
        with pytest.raises(TypeError, match="Class-based naming collision"):
            FilterArgumentsFactory(second).arguments
    finally:
        # Keep the class-level registry clean for other tests.
        FilterArgumentsFactory.input_object_types.pop(type_name, None)
        FilterArgumentsFactory._type_filterset_registry.pop(type_name, None)


def test_same_class_registered_twice_is_idempotent():
    """Registering the same FilterSet class twice is a no-op cache hit — no error, no warning.

    Replaces the previous ``test_no_collision_warning_for_same_filterset_same_prefix``.
    Validates the sibling branch of ``_check_collision``: same class, same type name,
    second call short-circuits through the cache.
    """
    type_name = FactFilterSet.type_name_for()
    FilterArgumentsFactory.input_object_types.pop(type_name, None)
    FilterArgumentsFactory._type_filterset_registry.pop(type_name, None)

    FilterArgumentsFactory(FactFilterSet).arguments  # prime the cache

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        FilterArgumentsFactory(FactFilterSet).arguments  # same class — idempotent
    assert not any("collision" in str(w.message).lower() for w in caught)

    FilterArgumentsFactory.input_object_types.pop(type_name, None)
    FilterArgumentsFactory._type_filterset_registry.pop(type_name, None)


def test_get_field_model_formfield():
    factory = FilterArgumentsFactory(FactFilterSet, "Fact")
    f_obj = MagicMock()
    f_obj.lookup_expr = "exact"
    f_obj.field_name = "name"
    f_obj.extra = {}
    f_obj.field = MagicMock()  # original field

    with (
        patch("django_graphene_filters.filter_arguments_factory.get_model_field") as mock_get_field,
        patch("django_graphene_filters.filter_arguments_factory.convert_form_field") as mock_convert,
    ):
        mock_model_field = MagicMock()
        mock_get_field.return_value = mock_model_field
        mock_convert.return_value = MagicMock()

        factory.get_field("name", f_obj)
        assert mock_model_field.formfield.called
