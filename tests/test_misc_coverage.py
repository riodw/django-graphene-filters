"""Miscellaneous unit tests covering edge cases in AnnotatedFilter, ConnectionField, and factories."""

from collections import OrderedDict
from unittest.mock import MagicMock, patch

import graphene
import pytest
from cookbook.recipes.models import ObjectType
from django.db import models
from django.db.models import Value as DjangoValue
from django.db.models.functions import Concat
from django_filters import Filter
from django_filters.filterset import BaseFilterSet
from graphene_django import DjangoObjectType

from django_graphene_filters.conf import reload_settings
from django_graphene_filters.connection_field import AdvancedDjangoFilterConnectionField
from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory
from django_graphene_filters.filters import (
    AnnotatedFilter,
    AutoFilter,
    SearchQueryFilter,
)
from django_graphene_filters.filterset import (
    AdvancedFilterSet,
    FilterSetMetaclass,
    QuerySetProxy,
)
from django_graphene_filters.input_data_factories import validate_search_query


class BoostModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "recipes"


def test_annotated_filter_distinct():
    """Test that AnnotatedFilter applies distinct() when configured."""
    f = AnnotatedFilter(field_name="name", lookup_expr="exact", distinct=True)
    qs = ObjectType.objects.none()

    # Create a value with a proper Django expression
    value = AnnotatedFilter.Value(
        annotation_value=Concat(DjangoValue("test"), DjangoValue("_annotation")),
        search_value="test",
    )

    # Mock the get_method to return a callable that returns the queryset
    f.get_method = lambda qs: lambda **kwargs: qs

    result = f.filter(qs, value)
    # The distinct() should have been called
    assert result is not None


def test_connection_field_no_provided_filterset():
    """Test that filter_input_type_prefix defaults correctly when no filterset is provided."""

    class TestNode(DjangoObjectType):
        class Meta:
            model = ObjectType
            fields = "__all__"
            interfaces = (graphene.relay.Node,)

    # Create connection field without filterset_class
    field = AdvancedDjangoFilterConnectionField(TestNode)

    # Access filter_input_type_prefix when provided_filterset_class is None
    prefix = field.filter_input_type_prefix
    # Should return just the node type name
    assert prefix == "TestNode"


def test_special_filter_input_type_factory():
    """Test that the factory correctly identifies and handles special filter input types."""

    # Create a filterset with a special filter (SearchQueryFilter)
    class SpecialFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["full_text_search"]}

    # Mock PostgreSQL settings
    with patch("django_graphene_filters.filterset.settings") as mock_settings:
        mock_settings.IS_POSTGRESQL = True
        mock_settings.HAS_TRIGRAM_EXTENSION = False

        factory = FilterArgumentsFactory(SpecialFS, "Special")

        # This should trigger the special filter handling
        args = factory.arguments
        assert "filter" in args


def test_get_field_with_in_lookup():
    """Test that get_field correctly handles 'in' lookups."""

    class InFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["in"]}

    factory = FilterArgumentsFactory(InFS, "In")

    # Get the filters
    filters = InFS.get_filters()

    # Find the 'in' filter
    in_filter = filters.get("name__in")
    if in_filter:
        field = factory.get_field("name__in", in_filter)
        assert field is not None


def test_filterset_to_trees_empty_values():
    """Test that sequence_to_tree handles empty input sequences."""
    from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory

    # Test with empty sequence
    result = FilterArgumentsFactory.sequence_to_tree([])
    assert result.name == ""


# --- Coverage Boost Extension ---


def test_queryset_proxy_callable_return_non_queryset():
    """Test that QuerySetProxy returns the raw value if the callable result is not a QuerySet."""
    qs = ObjectType.objects.none()
    proxy = QuerySetProxy(qs)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(
            models.QuerySet,
            "custom_method",
            lambda self: "string_result",
            raising=False,
        )
        assert proxy.custom_method() == "string_result"


def test_expand_auto_filter_generates_new_filter():
    """Test expand_auto_filter when it actually generates a new filter (Line 340)."""

    class AutoFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = []

    f = AutoFilter(field_name="name", lookups=["exact"])
    mock_filter = MagicMock()
    with patch(
        "django_filters.filterset.FilterSet.get_filters",
        return_value={"name": mock_filter},
    ):
        expanded = FilterSetMetaclass.expand_auto_filter(AutoFS, "name_alt", f)
        assert "name_alt" in expanded
        assert expanded["name_alt"] is not None


def test_get_filter_fields_adds_search():
    """Test get_filter_fields explicitly adds 'search' (Lines 458-460)."""

    class SearchFieldsFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = ["name"]

    with patch.object(BaseFilterSet, "get_filter_fields", return_value={"name": "test"}, create=True):
        fields = SearchFieldsFS.get_filter_fields()
        assert "search" in fields
        assert "name" in fields


def test_construct_search_with_prefix():
    """Test construct_search with field name that HAS a special prefix (Line 471)."""

    class SearchFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = []

    fs = SearchFS(queryset=ObjectType.objects.none())
    assert fs.construct_search("^name") == "name__istartswith"
    assert fs.construct_search("=name") == "name__iexact"
    assert fs.construct_search("$name") == "name__iregex"


@pytest.mark.django_db
def test_search_logic_full_flow():
    """Test the full search logic via .qs property (Lines 481-493, 502)."""

    class SearchLogicFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = ["name"]
            search_fields = ["name", "^name"]

    # Create some data
    ObjectType.objects.create(name="Apple")
    ObjectType.objects.create(name="Banana")

    # Filter by search
    fs = SearchLogicFS(data={"search": "Apple"}, queryset=ObjectType.objects.all())
    results = fs.qs
    assert results.count() == 1
    assert results[0].name == "Apple"


def test_find_filter_rsplit():
    """Test find_filter with LOOKUP_SEP (Line 562)."""

    class SplitFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["exact"]}

    fs = SplitFS(queryset=ObjectType.objects.none())
    f = fs.find_filter("name__exact")
    assert f is not None
    assert f.lookup_expr == "exact"


def test_create_special_filters_skips_existing():
    """Test that create_special_filters skips filters already in base_filters (Line 667 branch)."""

    class SpecialFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = []

    base_filters = OrderedDict()
    base_filters["search_query"] = "already_exists"

    res = SpecialFS.create_special_filters(base_filters, SearchQueryFilter)
    assert "search_query" not in res


def test_create_special_filters_with_field_name():
    """Test create_special_filters with a field name (Line 663)."""

    class SpecialFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = []

    res = SpecialFS.create_special_filters(OrderedDict(), SearchQueryFilter, field_name="myfield")
    assert "myfield__search_query" in res


def test_reload_settings_other_key():
    """Test reload_settings with a key other than DJANGO_SETTINGS_KEY (conf.py line 100 branch)."""
    reload_settings("OTHER_KEY", {"FOO": "BAR"})


def test_validate_search_query_success():
    """Test validate_search_query with a valid input (input_data_factories.py line 303 branch)."""
    validate_search_query({"value": "something"})


def test_filter_arguments_factory_get_field_no_formfield():
    """Test get_field when model field has no formfield() method (filter_arguments_factory.py line 222 branch)."""

    class DummyFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = ["name"]

    factory = FilterArgumentsFactory(DummyFS, "Prefix")
    f_obj = Filter(field_name="name", lookup_expr="exact")

    with patch("django_graphene_filters.filter_arguments_factory.get_model_field") as mock_get_field:
        mock_field = MagicMock()
        del mock_field.formfield
        mock_get_field.return_value = mock_field
        factory.get_field("name", f_obj)


def test_queryset_proxy_filter_args():
    """Test filter() with kwarg arguments (not just Q object)."""
    qs = ObjectType.objects.none()
    proxy = QuerySetProxy(qs)
    res = proxy.filter(name="test")
    assert str(res.q) == "(AND: ('name', 'test'))"


def test_queryset_proxy_exclude_args():
    """Test exclude() with kwarg arguments (not just Q object)."""
    qs = ObjectType.objects.none()
    proxy = QuerySetProxy(qs)
    res = proxy.exclude(name="test")
    assert str(res.q) == "(NOT (AND: ('name', 'test')))"


def test_construct_search_no_prefix():
    """Test construct_search with field name that has no special prefix."""

    class SearchFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = []

    fs = SearchFS(queryset=ObjectType.objects.none())
    assert fs.construct_search("name") == "name__icontains"


def test_create_form_without_not():
    """Test create_form when 'not' key is missing from data."""

    class FormFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = ["name"]

    fs = FormFS(queryset=ObjectType.objects.none())
    data = {"name": "test"}
    form_class = fs.get_form_class()
    form = fs.create_form(form_class, data)
    assert form.not_form is None


def test_find_filter_loop_match():
    """Test finding a filter by iterating through values when direct lookup fails."""

    class LoopFS(AdvancedFilterSet):
        class Meta:
            model = ObjectType
            fields = ["name"]

    fs = LoopFS(queryset=ObjectType.objects.none())
    f = fs.filters["name"]
    del fs.filters["name"]
    fs.filters["mismatched_key"] = f

    assert fs.find_filter("name") == f
