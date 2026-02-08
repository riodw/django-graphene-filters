from unittest.mock import MagicMock, patch

from django.db import models
from django_filters.filterset import FilterSet

from django_graphene_filters.filters import (
    AnnotatedFilter,
    RelatedFilter,
    SearchQueryFilter,
    SearchRankFilter,
    TrigramFilter,
)


class FilterTestModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "recipes"


def test_annotated_filter_name():
    f = AnnotatedFilter(field_name="test")
    assert "test_annotated" in f.annotation_name


def test_annotated_filter_logic():
    class MyFilter(AnnotatedFilter):
        postfix = "my"

    f = MyFilter(field_name="name", lookup_expr="exact")
    qs = FilterTestModel.objects.none()
    value = AnnotatedFilter.Value(annotation_value="annotated_val", search_value="search_val")

    # This will trigger QS.annotate and QS.filter
    with patch.object(models.QuerySet, "annotate", return_value=qs) as mock_annotate, patch.object(
        models.QuerySet, "filter", return_value=qs
    ) as mock_filter:

        f.filter(qs, value)
        assert mock_annotate.called
        assert mock_filter.called


def test_search_query_filter():
    f = SearchQueryFilter(field_name="name", lookup_expr="exact")
    assert f.postfix == "search_query"
    # Should call super().filter
    qs = FilterTestModel.objects.none()
    value = SearchQueryFilter.Value(annotation_value=MagicMock(), search_value=MagicMock())
    with patch("django_graphene_filters.filters.AnnotatedFilter.filter") as mock_super:
        f.filter(qs, value)
        mock_super.assert_called_once()


def test_search_rank_filter():
    f = SearchRankFilter(field_name="name", lookup_expr="exact")
    assert f.postfix == "search_rank"
    qs = FilterTestModel.objects.none()
    value = SearchRankFilter.Value(annotation_value=MagicMock(), search_value=0.8)
    with patch("django_graphene_filters.filters.AnnotatedFilter.filter") as mock_super:
        f.filter(qs, value)
        mock_super.assert_called_once()


def test_trigram_filter():
    f = TrigramFilter(field_name="name", lookup_expr="exact")
    assert f.postfix == "trigram"
    qs = FilterTestModel.objects.none()
    value = TrigramFilter.Value(annotation_value=MagicMock(), search_value=0.5)
    with patch("django_graphene_filters.filters.AnnotatedFilter.filter") as mock_super:
        f.filter(qs, value)
        mock_super.assert_called_once()


def test_related_filter_lazy_loading():
    class MockFS(FilterSet):
        class Meta:
            model = FilterTestModel
            fields = []

    # Test string path
    with patch("django_graphene_filters.filters.import_string", return_value=MockFS):
        f = RelatedFilter(filterset="path.to.MockFS")
        assert f.filterset == MockFS


def test_related_filter_lazy_loading_relative():
    class MockFS(FilterSet):
        class Meta:
            model = FilterTestModel
            fields = []

    f = RelatedFilter(filterset="MockFS")
    # Mock bound_filterset to simulate relative import
    bound_fs = MagicMock()
    bound_fs.__module__ = "my.module"
    f.bound_filterset = bound_fs

    with patch("django_graphene_filters.filters.import_string") as mock_import:
        # First call fails, triggers relative path
        mock_import.side_effect = [ImportError, MockFS]
        assert f.filterset == MockFS
        assert mock_import.call_args_list[1][0][0] == "my.module.MockFS"
