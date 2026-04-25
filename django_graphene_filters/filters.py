"""Additional filters for special lookups."""

from __future__ import annotations

import itertools
from typing import Any, NamedTuple

try:
    from django.contrib.postgres.search import (
        SearchQuery,
        SearchRank,
        SearchVector,
        TrigramDistance,
        TrigramSimilarity,
    )
except ImportError:  # pragma: no cover — psycopg2 / postgres not installed
    SearchQuery = None
    SearchRank = None
    SearchVector = None
    TrigramDistance = None
    TrigramSimilarity = None
from django.db import models
from django.db.models import QuerySet
from django.db.models.constants import LOOKUP_SEP
from django.http import HttpRequest
from django_filters import Filter
from django_filters.constants import EMPTY_VALUES
from django_filters.filterset import BaseFilterSet
from django_filters.rest_framework.filters import ModelChoiceFilter

from .mixins import LazyRelatedClassMixin

# Module-level counter for generating unique annotation names.
# Avoids mutable state on shared filter instances.
_annotation_counter = itertools.count()


class AnnotatedFilter(Filter):
    """A filter class that adds QuerySet annotations for advanced filtering.

    The filter allows the use of QuerySet annotations to apply filters dynamically
    based on a given value. It works for different types of lookups.
    """

    class Value(NamedTuple):
        annotation_value: Any
        search_value: Any

    # Postfix for generating unique annotation names
    postfix = "annotated"

    def filter(self, qs: models.QuerySet, value: Value) -> models.QuerySet:
        """Apply the filter to the QuerySet using annotation.

        Generates a QuerySet annotation and filters based on the generated annotation.
        """
        if value in EMPTY_VALUES:
            return qs
        if self.distinct:
            qs = qs.distinct()
        annotation_name = f"{self.field_name}_{self.postfix}_{next(_annotation_counter)}"
        qs = qs.annotate(**{annotation_name: value.annotation_value})
        lookup = f"{annotation_name}{LOOKUP_SEP}{self.lookup_expr}"
        return self.get_method(qs)(**{lookup: value.search_value})


class SearchQueryFilter(AnnotatedFilter):
    """A specialized `AnnotatedFilter` for performing full-text search.

    Full text search filter using the `SearchVector` and `SearchQuery` object.
    """

    class Value(NamedTuple):
        annotation_value: SearchVector
        search_value: SearchQuery

    postfix = "search_query"
    available_lookups = ("exact",)


class SearchRankFilter(AnnotatedFilter):
    """A specialized `AnnotatedFilter` for ranking search results.

    Full text search filter using the `SearchRank` object.
    """

    class Value(NamedTuple):
        annotation_value: SearchRank
        search_value: float

    postfix = "search_rank"
    available_lookups = ("exact", "gt", "gte", "lt", "lte")


class TrigramFilter(AnnotatedFilter):
    """A specialized `AnnotatedFilter` for trigram-based text search.

    This filter can be either similarity or distance-based.
    It performs full text search using similarity or distance of trigram.
    """

    class Value(NamedTuple):
        annotation_value: TrigramSimilarity | TrigramDistance
        search_value: float

    postfix = "trigram"
    available_lookups = ("exact", "gt", "gte", "lt", "lte")


class BaseRelatedFilter(LazyRelatedClassMixin):
    """Base class for related filters.

    A base filter class for related models. This class serves as the foundation for related filters.
    """

    def __init__(
        self,
        filterset: str | type[BaseFilterSet],
        *args,
        lookups: list[str] | None = None,
        **kwargs,
    ) -> None:
        self._has_explicit_queryset = kwargs.get("queryset") is not None
        super().__init__(*args, **kwargs)
        self._filterset = filterset
        self.lookups = lookups or []

    def bind_filterset(self, filterset: type[BaseFilterSet]) -> None:
        """Bind a filterset class to the current filter instance."""
        if not hasattr(self, "bound_filterset"):
            self.bound_filterset = filterset

    @property
    def filterset(self) -> type[BaseFilterSet]:
        """Lazy-load the filterset class if it is specified as a string."""
        self._filterset = self.resolve_lazy_class(self._filterset, getattr(self, "bound_filterset", None))
        return self._filterset

    @filterset.setter
    def filterset(self, value: type[BaseFilterSet]) -> None:
        self._filterset = value

    def get_queryset(self, request: HttpRequest) -> QuerySet:
        """Get the QuerySet for this filter.

        If no queryset was explicitly provided, derive one from the target
        filterset's ``Meta.model`` using ``.objects.all()``.
        """
        queryset = super().get_queryset(request)
        if queryset is None:
            # Auto-derive from the target filterset's model.
            # Use _default_manager instead of .objects to support models
            # that override the default manager name.
            # TODO(db-sharding, non-goal-in-first-pass): this form-validation
            # path has no caller queryset to inherit an alias from, so it
            # unconditionally hits the default DB. Follow-up: add a
            # shard-resolver hook (e.g. read ``request._db`` or a new
            # ``DJANGO_GRAPHENE_FILTERS["SHARD_RESOLVER"]``) and call
            # ``.using(...)`` accordingly. See
            # ``docs/spec-db_sharding.md`` → "Explicit non-goals".
            target = self.filterset
            model = getattr(getattr(target, "_meta", None), "model", None)
            if model:
                return model._default_manager.all()
        parent_name = getattr(getattr(self, "parent", None), "__class__", type(self)).__name__
        assert queryset is not None, (
            f"Expected .get_queryset() on related filter '{parent_name}.{self.field_name}'"
            " to return a `QuerySet`, but got `None`."
        )
        return queryset


class RelatedFilter(BaseRelatedFilter, ModelChoiceFilter):
    """A specialized filter class for related models.

    A ``ModelChoiceFilter`` that enables filtering across relationships by
    delegating to another FilterSet defined for the related model.  Example::

        class ManagerFilter(AdvancedFilterSet):
            class Meta:
                model = Manager
                fields = {"name": ["exact", "icontains"]}

        class DepartmentFilter(AdvancedFilterSet):
            manager = RelatedFilter(ManagerFilter, field_name="manager")

            class Meta:
                model = Department
                fields = {"name": ["exact", "icontains"]}

    The ``DepartmentFilter`` traverses the ``manager`` relationship using the
    ``__`` lookup separator, e.g. ``manager__name__icontains``.

    Attributes:
        filterset: The ``FilterSet`` that is traversed by this relationship.
            May be a class, an absolute import path, or the name of a class
            located in the same module as the origin filterset.
        lookups: A list of lookups to generate per-lookup filters for.
    """
