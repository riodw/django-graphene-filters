"""Additional filters for special lookups."""

from typing import Any, Callable, List, NamedTuple, Optional, Type, Union

from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramDistance,
    TrigramSimilarity,
)
from django.db import models
from django.db.models import QuerySet
from django.db.models.constants import LOOKUP_SEP
from django.http import HttpRequest
from django.utils.module_loading import import_string
from django_filters import Filter
from django_filters.constants import EMPTY_VALUES
from django_filters.filterset import BaseFilterSet
from django_filters.rest_framework.filters import ModelChoiceFilter


class AnnotatedFilter(Filter):
    """
    A filter class that adds QuerySet annotations for advanced filtering.

    The filter allows the use of QuerySet annotations to apply filters dynamically
    based on a given value. It works for different types of lookups.
    """

    class Value(NamedTuple):
        annotation_value: Any
        search_value: Any

    # Postfix for generating unique annotation names
    postfix = "annotated"

    def __init__(
        self,
        field_name: Optional[str] = None,
        lookup_expr: Optional[str] = None,
        *,
        label: Optional[str] = None,
        method: Optional[Union[str, Callable]] = None,
        distinct: bool = False,
        exclude: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(
            field_name,
            lookup_expr,
            label=label,
            method=method,
            distinct=distinct,
            exclude=exclude,
            **kwargs,
        )
        self.filter_counter = 0

    @property
    def annotation_name(self) -> str:
        """Return a unique name used for the annotation."""
        return f"{self.field_name}_{self.postfix}_{self.creation_counter}_{self.filter_counter}"

    def filter(self, qs: models.QuerySet, value: Value) -> models.QuerySet:
        """
        Apply the filter to the QuerySet using annotation.

        Generates a QuerySet annotation and filters based on the generated annotation.
        """
        if value in EMPTY_VALUES:
            return qs
        if self.distinct:
            qs = qs.distinct()
        annotation_name = self.annotation_name
        self.filter_counter += 1
        qs = qs.annotate(**{annotation_name: value.annotation_value})
        lookup = f"{annotation_name}{LOOKUP_SEP}{self.lookup_expr}"
        return self.get_method(qs)(**{lookup: value.search_value})


class SearchQueryFilter(AnnotatedFilter):
    """
    A specialized `AnnotatedFilter` for performing full-text search.

    Full text search filter using the `SearchVector` and `SearchQuery` object.
    """

    class Value(NamedTuple):
        annotation_value: SearchVector
        search_value: SearchQuery

    postfix = "search_query"
    available_lookups = ("exact",)

    def filter(self, qs: models.QuerySet, value: Value) -> models.QuerySet:
        """
        Apply full-text search filtering on the QuerySet.

        Uses the `SearchVector` and `SearchQuery` object.
        """
        return super().filter(qs, value)


class SearchRankFilter(AnnotatedFilter):
    """
    A specialized `AnnotatedFilter` for ranking search results.

    Full text search filter using the `SearchRank` object.
    """

    class Value(NamedTuple):
        annotation_value: SearchRank
        search_value: float

    postfix = "search_rank"
    available_lookups = ("exact", "gt", "gte", "lt", "lte")

    def filter(self, qs: models.QuerySet, value: Value) -> models.QuerySet:
        """Apply search ranking filtering on the QuerySet using the `SearchRank` object."""
        return super().filter(qs, value)


class TrigramFilter(AnnotatedFilter):
    """
    A specialized `AnnotatedFilter` for trigram-based text search.

    This filter can be either similarity or distance-based.
    It performs full text search using similarity or distance of trigram.
    """

    class Value(NamedTuple):
        annotation_value: Union[TrigramSimilarity, TrigramDistance]
        search_value: float

    postfix = "trigram"
    available_lookups = ("exact", "gt", "gte", "lt", "lte")

    def filter(self, qs: models.QuerySet, value: Value) -> models.QuerySet:
        """
        Apply the filter based on trigram similarity or distance on the QuerySet.

        Uses similarity or distance of trigram to perform the filtering.
        """
        return super().filter(qs, value)


class BaseRelatedFilter:
    """
    Base class for related filters.

    A base filter class for related models. This class serves as the foundation for related filters.
    """

    def __init__(
        self,
        filterset: Union[str, Type["BaseFilterSet"]],
        *args,
        lookups: Optional[List[str]] = None,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        # using private member to avoid collision with property method
        self.filterset = filterset
        self.lookups = lookups or []

    def bind_filterset(self, filterset: Type["BaseFilterSet"]) -> None:
        """Bind a filterset class to the current filter instance."""
        if not hasattr(self, "bound_filterset"):
            self.bound_filterset = filterset

    @property
    def filterset(self) -> Type["BaseFilterSet"]:
        """Lazy-load the filterset class if it is specified as a string."""
        if isinstance(self._filterset, str):
            try:
                # Assume absolute import path
                self._filterset = import_string(self._filterset)
            except ImportError:
                # Fallback to building import path relative to bind class
                path = ".".join([self.bound_filterset.__module__, self._filterset])
                self._filterset = import_string(path)
            return self._filterset

    @filterset.setter
    def filterset(self, value: Type["BaseFilterSet"]) -> None:
        self._filterset = value

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Get the QuerySet for this filter."""
        queryset = super().get_queryset(request)
        assert queryset is not None, (
            f"Expected .get_queryset() on related filter '{self.parent.__class__.__name__}.{self.field_name}'"
            " to return a `QuerySet`, but got `None`."
        )
        return queryset


class RelatedFilter(BaseRelatedFilter, ModelChoiceFilter):
    """A specialized filter class for related models.

    This filter allows for filtering across relationships by utilizing another FilterSet
    class defined for the related model.

    A `ModelChoiceFilter` that enables filtering across relationships.
    Take the following example:

        class ManagerFilter(filters.FilterSet):
            class Meta:
                model = Manager
                fields = {'name': ['exact', 'in', 'startswith']}

        class DepartmentFilter(filters.FilterSet):
            manager = RelatedFilter(ManagerFilter, queryset=managers)

            class Meta:
                model = Department
                fields = {'name': ['exact', 'in', 'startswith']}

    In the above, the `DepartmentFilter` can traverse the `manager`
    relationship with the `__` lookup seperator, accessing the filters of the
    `ManagerFilter` class. For example, the above would enable calls like:

        /api/managers?name=john%20doe
        /api/departments?manager__name=john%20doe

    Related filters function similarly to auto filters in that they can generate
    per-lookup filters. However, unlike auto filters, related filters are
    functional and not just placeholders. They will not be replaced by a
    generated `exact` filter.

    Attributes:
        filterset: The `FilterSet` that is traversed by this relationship.
            May be a class, an absolute import path, or the name of a class
            located in the same module as the origin filterset.
        lookups: A list of lookups to generate per-lookup filters for. This
            functions similarly to the `AutoFilter.lookups` argument.
    """
