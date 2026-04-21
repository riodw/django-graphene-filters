from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest
from django import forms
from django.db import models

from django_graphene_filters.conf import (
    DJANGO_SETTINGS_KEY,
    check_pg_trigram_extension,
    reload_settings,
)
from django_graphene_filters.filters import (
    AnnotatedFilter,
    RelatedFilter,
)
from django_graphene_filters.filterset import (
    AdvancedFilterSet,
    QuerySetProxy,
)


class FinalCoverageModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "recipes"


def test_queryset_proxy_misc():
    """Test miscellaneous QuerySetProxy behaviors like count, model access, and iteration."""
    qs = FinalCoverageModel.objects.none()
    proxy = QuerySetProxy(qs)
    # Callable attribute returning a non-QuerySet value — returned verbatim.
    assert proxy.count() == 0
    # Non-callable attribute access — returned via wrapt's ObjectProxy fallback.
    assert proxy.model == FinalCoverageModel
    # __iter__ yields [wrapped_qs, q].
    items = list(proxy)
    assert len(items) == 2


def test_tree_form_logic():
    """Validation logic and error handling for ``TreeFormMixin``."""

    class LeafForm(forms.Form):
        name = forms.CharField()

    leaf = LeafForm(data={})  # invalid
    leaf.is_valid()

    class TreeFS(AdvancedFilterSet):
        class Meta:
            model = FinalCoverageModel
            fields = ["name"]

    fs = TreeFS(queryset=FinalCoverageModel.objects.none())
    # Exercise the ``_form`` cache path by accessing ``fs.form`` twice.
    _ = fs.form
    _ = fs.form

    # Manually build a TreeForm to exercise init / clean / property.
    TreeForm = type("TreeForm", (LeafForm, AdvancedFilterSet.TreeFormMixin), {})
    form = TreeForm(data={}, and_forms=[leaf], not_form=leaf)
    fs._form = form

    # Error aggregation loops over ``and_forms``.
    assert "name" in fs.errors["and"]["and_0"]
    # ``not_form`` errors appear under the NOT_KEY.
    assert "name" in fs.errors["not"]
    # ``not_form`` is exposed on the built form instance.
    assert fs.form.not_form == leaf


def test_find_filter_fallback_loop():
    """``find_filter`` falls back to iterating filter values when key lookup fails."""

    class FallbackFS(AdvancedFilterSet):
        class Meta:
            model = FinalCoverageModel
            fields = ["name"]

    fs = FallbackFS(queryset=FinalCoverageModel.objects.none())
    # Move filter to a different key
    f = fs.filters.pop("name")
    fs.filters["fake_key"] = f
    assert fs.find_filter("name") == f
    # Non-existent — now raises KeyError with a descriptive message
    with pytest.raises(KeyError, match="No filter found for data key 'missing'"):
        fs.find_filter("missing")


def test_create_filters_pg_trigram_loop():
    """Full-text search filter creation when the Trigram extension is enabled."""
    mock_settings = MagicMock()
    mock_settings.IS_POSTGRESQL = True
    mock_settings.HAS_TRIGRAM_EXTENSION = True

    class FullFS(AdvancedFilterSet):
        class Meta:
            model = FinalCoverageModel
            fields = {"name": ["full_text_search"]}

    with patch("django_graphene_filters.filterset.settings", mock_settings):
        # SearchQueryFilter / SearchRankFilter use ``field_name=None`` in the
        # create_special_filters call; Trigram iterates per field name.
        res = FullFS.create_full_text_search_filters(OrderedDict())
        assert "name__trigram" in str(res.keys())


def test_filters_gaps():
    """Miscellaneous edge cases for ``AnnotatedFilter`` and ``RelatedFilter``."""
    # AnnotatedFilter with an empty value returns the queryset unchanged.
    f = AnnotatedFilter(field_name="name", lookup_expr="exact")
    result = f.filter(FinalCoverageModel.objects.none(), [])
    # Check that it returns a QuerySet (comparison of QuerySets doesn't work with ==)
    assert hasattr(result, "model") and result.model == FinalCoverageModel

    # RelatedFilter ``filterset`` setter writes through to ``_filterset``.
    rf = RelatedFilter(filterset="path")
    rf.filterset = "new_path"
    assert rf._filterset == "new_path"


def test_conf_extension_checks():
    """``check_pg_trigram_extension`` detection + ``reload_settings`` round-trip."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [1]
    with patch(
        "django.db.connection.cursor",
        return_value=MagicMock(__enter__=lambda s: mock_cursor),
    ):
        assert check_pg_trigram_extension() is True

    from django_graphene_filters import conf

    old_settings = conf.settings
    try:
        reload_settings(DJANGO_SETTINGS_KEY, None)
    finally:
        conf.settings = old_settings


def test_arg_factory_basic_props():
    """Test that retrieving arguments property from FilterArgumentsFactory returns non-empty dict."""
    # Test FilterArgumentsFactory with a simple filterset
    from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory

    class DummyFS(AdvancedFilterSet):
        class Meta:
            model = FinalCoverageModel
            fields = {"name": ["exact", "icontains"]}

    factory = FilterArgumentsFactory(DummyFS)
    res = factory.arguments  # Access as property, not method
    assert len(res) > 0
