"""`AdvancedFilterSet` class module.

https://github.com/devind-team/graphene-django-filter
Use the `AdvancedFilterSet` class from this module instead of the `FilterSet` from django-filter.
"""
import copy
import warnings
from collections import OrderedDict
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

from django.db import connection, models
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

        # Only expand the auto filters if a model is defined for the new class.
        # Model may be undefined for mixins.
        if new_class._meta.model is not None:
            for name, f in new_class.related_filters.items():
                expanded = cls.expand_auto_filter(new_class, name, f)
                new_class.base_filters.update(expanded)

        return new_class

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

        for gen_name, gen_f in new_class.get_filters().items():
            # get_filters() generates param names from the model field name, so
            # Replace the model field name with the attribute name from the FilterSet
            gen_name = gen_name.replace(f.field_name, filter_name, 1)

            # do not overwrite declared filters
            # Add to expanded filters if it's not an explicitly declared filter
            if gen_name not in orig_declared:
                expanded[gen_name] = gen_f

        # restore reference to original attributes (opts/declared filters)
        new_class._meta, new_class.declared_filters = orig_meta, orig_declared

        return expanded


class AdvancedFilterSet(filterset.BaseFilterSet, metaclass=FilterSetMetaclass):
    """Allow you to use advanced filters."""

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
            not_form=self.create_form(form_class, data["not"])
            if data.get("not")
            else None,
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
    def get_filters(cls) -> OrderedDict:
        """Get all filters for the filterset.

        This is the combination of declared and generated filters.
        """
        filters = super().get_filters()
        if not cls._meta.model:
            return filters

        return OrderedDict(
            [
                *filters.items(),
                *cls.create_full_text_search_filters(filters).items(),
            ]
        )

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
    def _get_fields(cls, predicate: Callable[[str], bool]) -> OrderedDict:
        """Resolve the `Meta.fields` argument including lookups that match the predicate."""
        fields: List[Tuple[str, List[str]]] = []

        for related_name in cls.related_filters:
            rf = cls.related_filters[related_name]
            f = rf._filterset.get_fields()
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
