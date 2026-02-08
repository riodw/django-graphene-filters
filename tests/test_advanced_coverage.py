from collections import OrderedDict
from unittest.mock import MagicMock, patch

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
    # Line 96: return result (non-QuerySet)
    assert proxy.count() == 0
    # Line 79 (now fixed/different): non-callable attr
    assert proxy.model == FinalCoverageModel
    # Line 100-107: __iter__
    items = list(proxy)
    assert len(items) == 2


def test_tree_form_logic():
    """Test the validation logic and error handling of TreeFormMixin."""

    # Targets TreeFormMixin and TreeFilterForm (lines 386, 445, 450, 458, 471, 481-493, 502)
    class LeafForm(forms.Form):
        name = forms.CharField()

    leaf = LeafForm(data={})  # invalid
    leaf.is_valid()

    class TreeFS(AdvancedFilterSet):
        class Meta:
            model = FinalCoverageModel
            fields = ["name"]

    fs = TreeFS(queryset=FinalCoverageModel.objects.none())
    # Line 386: hit hasattr(self, "_form")
    _ = fs.form
    _ = fs.form

    # Manually build a TreeForm to hit init/clean/property
    TreeForm = type("TreeForm", (LeafForm, AdvancedFilterSet.TreeFormMixin), {})
    form = TreeForm(data={}, and_forms=[leaf], not_form=leaf)
    fs._form = form

    # Line 445: loops over and_forms
    assert "name" in fs.errors["and"]["and_0"]
    # Line 450: not_form check
    assert "name" in fs.errors["not"]
    # Line 471: not_form property
    assert fs.form.not_form == leaf

    # Line 458-461: form validation is already tested above


def test_find_filter_fallback_loop():
    """Test that find_filter falls back to iterating values if key lookup fails."""

    # Hit line 572-573
    class FallbackFS(AdvancedFilterSet):
        class Meta:
            model = FinalCoverageModel
            fields = ["name"]

    fs = FallbackFS(queryset=FinalCoverageModel.objects.none())
    # Move filter to a different key
    f = fs.filters.pop("name")
    fs.filters["fake_key"] = f
    assert fs.find_filter("name") == f
    # Non-existent
    assert fs.find_filter("missing") is None


def test_create_filters_pg_trigram_loop():
    """Test creation of full text search filters when Trigram extension is enabled."""
    # Hit line 631 and 667
    mock_settings = MagicMock()
    mock_settings.IS_POSTGRESQL = True
    mock_settings.HAS_TRIGRAM_EXTENSION = True

    class FullFS(AdvancedFilterSet):
        class Meta:
            model = FinalCoverageModel
            fields = {"name": ["full_text_search"]}

    with patch("django_graphene_filters.filterset.settings", mock_settings):
        # 667: field_name is None for SearchQueryFilter/SearchRankFilter
        res = FullFS.create_full_text_search_filters(OrderedDict())
        assert "name__trigram" in str(res.keys())


def test_filters_gaps():
    """Test miscellaneous edge cases for AnnotatedFilter and RelatedFilter."""
    # AnnotatedFilter line 73: empty values
    f = AnnotatedFilter(field_name="name", lookup_expr="exact")
    result = f.filter(FinalCoverageModel.objects.none(), [])
    # Check that it returns a QuerySet (comparison of QuerySets doesn't work with ==)
    assert hasattr(result, "model") and result.model == FinalCoverageModel

    # RelatedFilter setter 190
    rf = RelatedFilter(filterset="path")
    rf.filterset = "new_path"
    assert rf._filterset == "new_path"


def test_conf_extension_checks():
    """Test the PostgreSQL Trigram extension check and settings reload."""
    # conf.py 47-51, 100-101
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

    factory = FilterArgumentsFactory(DummyFS, "Test")
    res = factory.arguments  # Access as property, not method
    assert len(res) > 0
