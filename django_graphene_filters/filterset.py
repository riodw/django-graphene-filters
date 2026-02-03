"""`AdvancedFilterSet` class module.

https://github.com/devind-team/graphene-django-filter
Use the `AdvancedFilterSet` class from this module instead of the `FilterSet` from django-filter.
"""

import copy
import operator
import warnings
from collections import OrderedDict
from graphene import String  # GraphQL String type

from typing import (
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
    Union,
    cast,
)
from functools import reduce

from django.db import connection, models
from django.db.models import Q
from django.db.models.constants import LOOKUP_SEP
from django.forms import Form
from django.forms.utils import ErrorDict
from django_filters import Filter
from django_filters import filterset
from django_filters.conf import settings as django_settings
from django_filters.utils import get_model_field
from wrapt import ObjectProxy

from . import filters, utils
from .conf import settings


class QuerySetProxy(ObjectProxy):
    """
    Proxy class for Django QuerySet object.

    This class allows us to work with the Django QuerySet in a way
    that also considers the 'Q' object for complex queries.

    The Django-filter library works with QuerySet objects,
    but such objects do not provide the ability to apply the negation operator to the entire object.
    Therefore, it is convenient to work with the Q object instead of the QuerySet.
    This class replaces the original QuerySet object,
    and creates a Q object when calling the `filter` and `exclude` methods.
    """

    __slots__ = "q"

    def __init__(self, wrapped: models.QuerySet, q: Optional[models.Q] = None) -> None:
        super().__init__(wrapped)
        self.q = q or models.Q()

    def __getattr__(self, name: str) -> Any:
        """
        Override QuerySet attribute access behavior for all cases except `filter` and `exclude`.

        Args:
            name: Name of the attribute to access.

        Returns:
            Modified or original attribute depending on the name.
        """
        if name == "filter":
            return self.filter_
        elif name == "exclude":
            return self.exclude_
        attr = super().__getattr__(name)
        if callable(attr):
            return self._make_callable_proxy(attr)
        return attr

    def _make_callable_proxy(self, attr: Callable) -> Callable:
        """
        Wrap callable attributes to return a QuerySetProxy when a QuerySet is returned.

        Args:
            attr: Callable attribute from the wrapped QuerySet.

        Returns:
            A wrapped callable.
        """

        def func(*args, **kwargs) -> Any:
            result = attr(*args, **kwargs)
            if isinstance(result, models.QuerySet):
                return QuerySetProxy(result, self.q)
            return result

        return func

    def __iter__(self) -> Iterator[Any]:
        """
        Allow iteration over the proxy.

        Returns:
            An iterator for the wrapped QuerySet and the Q object.
        """
        return iter([self.__wrapped__, self.q])

    def filter_(self, *args, **kwargs) -> "QuerySetProxy":
        """
        Override the 'filter' method of QuerySet.

        Args:
            args, kwargs: Arguments passed to the filter.

        Returns:
            Updated QuerySetProxy instance.
        """
        if len(kwargs) == 0 and len(args) == 1 and isinstance(args[0], models.Q):
            q = args[0]
        else:
            q = models.Q(*args, **kwargs)
        self.q &= q  # Update existing Q object
        return self

    def exclude_(self, *args, **kwargs) -> "QuerySetProxy":
        """
        Override the 'exclude' method of QuerySet.

        Args:
            args, kwargs: Arguments passed to the exclude.

        Returns:
            Updated QuerySetProxy instance.
        """
        if len(kwargs) == 0 and len(args) == 1 and isinstance(args[0], models.Q):
            q = args[0]
        else:
            q = models.Q(*args, **kwargs)
        self.q &= ~q  # Update existing Q object using negation
        return self


def is_full_text_search_lookup_expr(lookup_expr: str) -> bool:
    """
    Determine if the given lookup_expression is a full text search expression.

    Args:
        lookup_expr (str): The lookup expression to be checked.

    Returns:
        bool: True if it is a full-text search expression, False otherwise.
    """
    return lookup_expr.split(LOOKUP_SEP)[-1] == "full_text_search"


def is_regular_lookup_expr(lookup_expr: str) -> bool:
    """
    Determine if the lookup_expr must be processed in a regular way.

    Args:
        lookup_expr (str): The lookup expression to be checked.

    Returns:
        bool: True if it should be processed normally, False otherwise.
    """
    # Add any other special lookup expressions to this list as the need arises.
    return not any(
        [is_full_text_search_lookup_expr(lookup_expr)],
    )


class FilterSetMetaclass(filterset.FilterSetMetaclass):
    """
    Custom metaclass for creating FilterSet classes.

    Extends the behavior of the FilterSetMetaclass from the
    `rest_framework_filters` package. It specifically enriches the creation
    of FilterSet classes with additional attributes and logic to deal with
    related filters and auto-filters based on lookup methods.

    Attributes:
        related_filters (OrderedDict): Stores filters that are of type
            BaseRelatedFilter.

    Methods:
        expand_auto_filter: Resolves an `AutoFilter` or `BaseRelatedFilter`
            into individual filters based on supported lookup methods.

    """

    def __new__(
        cls: Type["FilterSetMetaclass"],
        name: str,
        bases: tuple,
        attrs: Dict[str, Any],
    ) -> "FilterSetMetaclass":
        """
        Overridden __new__ method to extend the FilterSet class creation logic.

        Args:
            name (str): The name of the new class.
            bases (tuple): A tuple of base classes.
            attrs (Dict[str, Any]): A dictionary of attributes for the new class.

        Returns:
            FilterSetMetaclass: A new FilterSetMetaclass object.
        """

        # Allow users to use `filter_fields` instead of `fields` in Meta
        # to match graphene-django conventions.
        meta_class = attrs.get("Meta")
        if meta_class:
            if hasattr(meta_class, "filter_fields") and not hasattr(
                meta_class, "fields"
            ):
                # Map filter_fields to fields so django-filter can process it normally
                setattr(meta_class, "fields", meta_class.filter_fields)

        # Create the new class using the parent class's __new__ method
        new_class = super().__new__(cls, name, bases, attrs)

        # Populate related_filters with filters of type BaseRelatedFilter
        new_class.related_filters = OrderedDict(
            [
                (name, f)
                for name, f in new_class.declared_filters.items()
                if isinstance(f, filters.BaseRelatedFilter)
            ]
        )

        # Bind filters to the new class
        # See: :meth:`rest_framework_filters.filters.RelatedFilter.bind`
        for f in new_class.related_filters.values():
            f.bind_filterset(new_class)

        # DEFER EXPANSION:
        # We removed the immediate expansion loop here to allow for
        # circular dependencies in the same file. Expansion now happens
        # in AdvancedFilterSet.get_filters().

        return new_class

    @classmethod
    def expand_related_filter(
        cls,
        new_class: "FilterSetMetaclass",
        filter_name: str,
        f: filters.BaseRelatedFilter,
    ) -> Dict[str, "Filter"]:
        """
        Expand a RelatedFilter by grabbing filters from the target FilterSet.
        """
        expanded = OrderedDict()

        # 1. Get the target FilterSet class
        target_filterset = f.filterset

        if not target_filterset:
            return expanded

        # Get filters from the target
        # We trigger get_filters() on the target to ensure it is also expanded
        target_filters = target_filterset.get_filters()

        # 2. Get filters from the target
        # We trigger get_filters() on the target to ensure it is also expanded
        for name, field in target_filters.items():
            # Skip full text search generated filters to avoid noise/recursion issues if needed
            # or include them if desired. For now, we include everything.

            # Create the new nested name (e.g., 'attributes__name')
            new_name = f"{filter_name}{LOOKUP_SEP}{name}"

            # Clone the filter to avoid modifying the original instance
            # (Optional but recommended to prevent side effects)
            field_copy = copy.deepcopy(field)

            # Update the field_name to point to the relationship path
            # e.g. "name" becomes "xxx__name" so the ORM knows the path
            field_copy.field_name = f"{f.field_name}{LOOKUP_SEP}{field.field_name}"

            # Add to expanded
            expanded[new_name] = field_copy

        return expanded

    @classmethod
    def expand_auto_filter(
        cls: Type["FilterSetMetaclass"],
        new_class: "FilterSetMetaclass",
        filter_name: str,
        f: filters.BaseRelatedFilter,
    ) -> Dict[str, "Filter"]:
        """
        Resolve an `AutoFilter` or `BaseRelatedFilter` into individual filters based on lookup methods.

        This method name is slightly inaccurate since it handles both
        :class:`rest_framework_filters.filters.AutoFilter` and
        :class:`rest_framework_filters.filters.BaseRelatedFilter`, as well as
        their subclasses, which all support per-lookup filter generation.

        Args:
            new_class: The `FilterSetMetaclass` class to generate filters for.
            filter_name (str): The attribute name of the filter on the `FilterSet`.
            f: The filter instance to expand.

        Returns:
            Dict[str, Filter]: A dictionary of expanded filters.
        """
        expanded = OrderedDict()

        # Make deep copies to avoid modifying original attributes
        # get reference to opts/declared filters so originals aren't modified
        orig_meta, orig_declared = new_class._meta, new_class.declared_filters
        new_class._meta = copy.deepcopy(new_class._meta)
        new_class.declared_filters = {}

        # Use meta.fields to generate auto filters
        new_class._meta.fields = {f.field_name: f.lookups or []}

        try:
            # We call super().get_filters() to use standard django-filter generation
            # We cannot call new_class.get_filters() here if we override it below
            # so we might need a workaround or assume AutoFilter is simple.

            # Since AdvancedFilterSet overrides get_filters, we need to be careful.
            # However, expand_auto_filter is legacy/compatibility.
            # We rely on the fact that super().get_filters() calculates based on meta.fields.
            gen_filters = super(AdvancedFilterSet, new_class).get_filters()

            for gen_name, gen_f in gen_filters.items():
                # get_filters() generates param names from the model field name, so
                # Replace the model field name with the attribute name from the FilterSet
                gen_name = gen_name.replace(f.field_name, filter_name, 1)

                # do not overwrite declared filters
                # Add to expanded filters if it's not an explicitly declared filter
                if gen_name not in orig_declared:
                    expanded[gen_name] = gen_f
        except Exception:
            # Swallow TypeError if field doesn't exist on model (e.g. reverse relation)
            # This allows safe failover if you accidentally use expand_auto_filter
            pass

        # restore reference to original attributes (opts/declared filters)
        new_class._meta, new_class.declared_filters = orig_meta, orig_declared

        return expanded


# Define the lookup prefixes, similar to DRF
LOOKUP_PREFIXES = {
    "^": "istartswith",
    "=": "iexact",
    "@": "search",
    "$": "iregex",
}


class AdvancedFilterSet(filterset.BaseFilterSet, metaclass=FilterSetMetaclass):
    """Allow you to use advanced filters."""

    # Cache for expanded filters
    _expanded_filters = None
    # Flag to prevent infinite recursion in get_filters
    _is_expanding_filters = False


    @classmethod
    def get_filters(cls) -> OrderedDict:
        """
        Get all filters for the filterset.
        This method is overridden to perform LAZY expansion of RelatedFilters.
        """
        # If we have already expanded and cached, return it.
        # Note: We must be careful with inheritance, but get_filters is usually called on the final class.
        if getattr(cls, "_expanded_filters", None) is not None:
            return cls._expanded_filters

        # RECURSION PROTECTION:
        # If we are already currently expanding this class, return the base filters
        # (native fields) immediately. This stops the infinite loop when
        # Attribute -> Value -> Attribute tries to resolve.
        if cls._is_expanding_filters:
            return super().get_filters()

        cls._is_expanding_filters = True

        try:
            # 1. Get standard filters (declared + Meta.fields generated)
            # We call super() to get the base django-filter behavior
            all_filters = super().get_filters()

            # 2. Expand RelatedFilters (Lazily)
            if cls._meta.model is not None:
                # We use the Metaclass helper methods
                related_filters_val = getattr(cls, "related_filters", OrderedDict())
                for name, f in related_filters_val.items():
                    if isinstance(f, filters.RelatedFilter):
                        expanded = cls.__class__.expand_related_filter(cls, name, f)
                    else:
                        expanded = cls.__class__.expand_auto_filter(cls, name, f)
                    all_filters.update(expanded)

            # 3. Add Full Text Search filters
            all_filters = OrderedDict(
                [
                    *all_filters.items(),
                    *cls.create_full_text_search_filters(all_filters).items(),
                ]
            )

            # Cache the result on the class to avoid re-calculation
            # cls._expanded_filters = all_filters
            return all_filters
        finally:
            # CRITICAL: Reset the flag so future calls (e.g. in other FilterSets)
            # can actually perform expansion.
            cls._is_expanding_filters = False

    class TreeFormMixin(Form):
        """Tree-like form mixin."""

        def __init__(
            self,
            and_forms: Optional[List["AdvancedFilterSet.TreeFormMixin"]] = None,
            or_forms: Optional[List["AdvancedFilterSet.TreeFormMixin"]] = None,
            not_form: Optional["AdvancedFilterSet.TreeFormMixin"] = None,
            *args,
            **kwargs,
        ) -> None:
            super().__init__(*args, **kwargs)
            self.and_forms = and_forms or []
            self.or_forms = or_forms or []
            self.not_form = not_form

        @property
        def errors(self) -> ErrorDict:
            """Return an ErrorDict for the data provided for the form."""
            self_errors: ErrorDict = super().errors
            for key in ("and", "or"):
                errors: ErrorDict = ErrorDict()
                for i, form in enumerate(getattr(self, f"{key}_forms")):
                    if form.errors:
                        errors[f"{key}_{i}"] = form.errors
                if len(errors):
                    self_errors.update({key: errors})
            if self.not_form and self.not_form.errors:
                self_errors.update({"not": self.not_form.errors})
            return self_errors

    @classmethod
    def get_filter_fields(cls):
        """
        Ensure 'search' is added to the filter input type.
        """
        fields = super().get_filter_fields()  # Get existing filter fields
        fields["search"] = String()  # Explicitly add 'search' as a String type
        return fields

    # Search_fields code
    def get_search_fields(self):
        """Retrieve the search_fields attribute from Meta."""
        return getattr(self.Meta, "search_fields", None)

    def construct_search(self, field_name):
        """Constructs the search query lookup based on prefixes."""
        lookup = LOOKUP_PREFIXES.get(field_name[0], "icontains")
        if field_name[0] in LOOKUP_PREFIXES:
            field_name = field_name[1:]  # Strip prefix if exists
        return f"{field_name}__{lookup}"

    def build_search_conditions(self, queryset, search_query):
        """Constructs Q objects for search terms across search_fields."""
        search_fields = self.get_search_fields()
        if not search_fields or not search_query:
            return queryset

        # Split terms to handle multiple terms (quoted and non-quoted)
        search_terms = search_query.split()
        orm_lookups = [self.construct_search(field) for field in search_fields]

        # Construct combined Q object for all terms and fields
        search_conditions = Q()
        for term in search_terms:
            term_conditions = reduce(
                operator.or_, (Q(**{lookup: term}) for lookup in orm_lookups)
            )
            search_conditions &= term_conditions

        # Apply the filter to the queryset
        return queryset.filter(search_conditions)

    @property
    def qs(self):
        queryset = super().qs  # Retrieve the base queryset
        # Check if 'search' is part of the data and apply it if present
        search_query = self.data.get("search")
        if search_query:
            # Apply search filter if search_query exists
            queryset = self.build_search_conditions(queryset, search_query)
        return queryset

    # Filters
    def get_form_class(self) -> Type[Union[Form, TreeFormMixin]]:
        """
        Return a django Form class suitable of validating the filterset data.

        The form must be tree-like because the data is tree-like.
        """
        form_class = super(AdvancedFilterSet, self).get_form_class()
        tree_form = cast(
            Type[Union[Form, AdvancedFilterSet.TreeFormMixin]],
            type(
                f'{form_class.__name__.replace("Form", "")}TreeForm',
                (form_class, AdvancedFilterSet.TreeFormMixin),
                {},
            ),
        )
        return tree_form

    @property
    def form(self) -> Union[Form, TreeFormMixin]:
        """Return a django Form suitable of validating the filterset data."""
        if not hasattr(self, "_form"):
            form_class = self.get_form_class()
            if self.is_bound:
                self._form = self.create_form(form_class, self.data)
            else:
                self._form = form_class(prefix=self.form_prefix)
        return self._form

    def create_form(
        self,
        form_class: Type[Union[Form, TreeFormMixin]],
        data: Dict[str, Any],
    ) -> Union[Form, TreeFormMixin]:
        """Create a form from a form class and data."""
        return form_class(
            data={k: v for k, v in data.items() if k not in ("and", "or", "not")},
            and_forms=[
                self.create_form(form_class, and_data)
                for and_data in data.get("and", [])
            ],
            or_forms=[
                self.create_form(form_class, or_data) for or_data in data.get("or", [])
            ],
            not_form=(
                self.create_form(form_class, data["not"]) if data.get("not") else None
            ),
        )

    def find_filter(self, data_key: str) -> Filter:
        """Find a filter using a data key.

        The data key may differ from a filter name, because
        the data keys may contain DEFAULT_LOOKUP_EXPR and user can create
        a AdvancedFilterSet class without following the naming convention.
        """
        if LOOKUP_SEP in data_key:
            field_name, lookup_expr = data_key.rsplit(LOOKUP_SEP, 1)
        else:
            field_name, lookup_expr = data_key, django_settings.DEFAULT_LOOKUP_EXPR
        key = (
            field_name
            if lookup_expr == django_settings.DEFAULT_LOOKUP_EXPR
            else data_key
        )
        if key in self.filters:
            return self.filters[key]
        for filter_value in self.filters.values():
            if (
                filter_value.field_name == field_name
                and filter_value.lookup_expr == lookup_expr
            ):
                return filter_value

    def filter_queryset(self, queryset: models.QuerySet) -> models.QuerySet:
        """Filter a queryset with a top level form's `cleaned_data`."""
        qs, q = self.get_queryset_proxy_for_form(queryset, self.form)
        # rest_framework_filters/filterset.py:318
        return qs.filter(q)

    def get_queryset_proxy_for_form(
        self,
        queryset: models.QuerySet,
        form: Union[Form, TreeFormMixin],
    ) -> QuerySetProxy:
        """Return a `QuerySetProxy` object for a form's `cleaned_data`."""
        qs = queryset
        q = models.Q()
        for name, value in form.cleaned_data.items():
            qs, q = self.find_filter(name).filter(QuerySetProxy(qs, q), value)
        and_q = models.Q()
        for and_form in form.and_forms:
            qs, new_q = self.get_queryset_proxy_for_form(qs, and_form)
            and_q = and_q & new_q
        or_q = models.Q()
        for or_form in form.or_forms:
            qs, new_q = self.get_queryset_proxy_for_form(qs, or_form)
            or_q = or_q | new_q
        if form.not_form:
            qs, new_q = self.get_queryset_proxy_for_form(queryset, form.not_form)
            not_q = ~new_q
        else:
            not_q = models.Q()
        return QuerySetProxy(qs, q & and_q & or_q & not_q)


    @classmethod
    def create_full_text_search_filters(
        cls,
        base_filters: OrderedDict,
    ) -> OrderedDict:
        """Create available full text search filters."""
        new_filters = OrderedDict()
        full_text_search_fields = cls.get_full_text_search_fields()
        if not len(full_text_search_fields):
            return new_filters
        if not settings.IS_POSTGRESQL:
            warnings.warn(
                f"Full text search is not available because the {connection.vendor} vendor is "
                "used instead of the postgresql vendor.",
            )
            return new_filters
        from .filters import SearchQueryFilter, SearchRankFilter, TrigramFilter

        new_filters = OrderedDict(
            [
                *new_filters.items(),
                *cls.create_special_filters(base_filters, SearchQueryFilter).items(),
                *cls.create_special_filters(base_filters, SearchRankFilter).items(),
            ]
        )
        if not settings.HAS_TRIGRAM_EXTENSION:
            warnings.warn(
                "Trigram search is not available because the `pg_trgm` extension is not installed.",
            )
            return new_filters
        for field_name in full_text_search_fields:
            new_filters = OrderedDict(
                [
                    *new_filters.items(),
                    *cls.create_special_filters(
                        base_filters, TrigramFilter, field_name
                    ).items(),
                ]
            )
        return new_filters

    @classmethod
    def create_special_filters(
        cls,
        base_filters: OrderedDict,
        filter_class: Union[Type[Filter], Any],
        field_name: Optional[str] = None,
    ) -> OrderedDict:
        """Create special filters using a filter class and a field name."""
        new_filters = OrderedDict()
        for lookup_expr in filter_class.available_lookups:
            if field_name:
                postfix_field_name = f"{field_name}{LOOKUP_SEP}{filter_class.postfix}"
            else:
                postfix_field_name = filter_class.postfix
            filter_name = cls.get_filter_name(postfix_field_name, lookup_expr)
            if filter_name not in base_filters:
                new_filters[filter_name] = filter_class(
                    field_name=postfix_field_name,
                    lookup_expr=lookup_expr,
                )
        return new_filters

    @classmethod
    def get_fields(cls) -> OrderedDict:
        """Resolve the `Meta.fields` argument including only regular lookups."""
        return cls._get_fields(is_regular_lookup_expr)

    @classmethod
    def get_full_text_search_fields(cls) -> OrderedDict:
        """Resolve the `Meta.fields` argument including only full text search lookups."""
        return cls._get_fields(is_full_text_search_lookup_expr)

    @classmethod
    def _get_fields(
        cls, predicate: Callable[[str], bool], visited: Optional[set[Type]] = None
    ) -> OrderedDict:
        """
        Resolve the `Meta.fields` argument including lookups that match the predicate.
        Includes recursion protection for circular dependencies.
        """
        if visited is None:
            visited = set()

        # Stop recursion if we have visited this class already
        if cls in visited:
            return OrderedDict()

        visited.add(cls)

        if not cls._meta.model:
            return OrderedDict()

        fields: List[Tuple[str, List[str]]] = []

        related_filters_val = getattr(cls, "related_filters", OrderedDict())
        for related_name in related_filters_val:
            rf = related_filters_val[related_name]

            # Use .filterset property to resolve string references
            f_class = rf.filterset

            # Recursive call with visited set
            if f_class and issubclass(f_class, AdvancedFilterSet):
                f = f_class._get_fields(predicate, visited)
            elif f_class:
                # Fallback for standard FilterSets
                f = f_class.get_fields()
            else:
                f = {}

            for key, value in f.items():
                fields.append((related_name + "__" + key, value))

        for k, v in super().get_fields().items():
            if v == "__all__":
                field = get_model_field(cls._meta.model, k)
                if field is not None:
                    fields.append((k, utils.lookups_for_field(field)))
                else:
                    fields.append((k, []))
            else:
                regular_field = [
                    lookup_expr for lookup_expr in v if predicate(lookup_expr)
                ]
                if len(regular_field):
                    fields.append((k, regular_field))
        return OrderedDict(fields)
