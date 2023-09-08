"""
`AdvancedFilterSet` class module.
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


def related(filterset, filter_name):
    # Return a related filter_name, using the filterset relationship if present.
    if not filterset.relationship:
        return filter_name
    return LOOKUP_SEP.join([filterset.relationship, filter_name])


class QuerySetProxy(ObjectProxy):
    """Proxy for a QuerySet object.

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
        """Return QuerySet attributes for all cases except `filter` and `exclude`."""
        if name == "filter":
            return self.filter_
        elif name == "exclude":
            return self.exclude_
        attr = super().__getattr__(name)
        if callable(attr):

            def func(*args, **kwargs) -> Any:
                result = attr(*args, **kwargs)
                if isinstance(result, models.QuerySet):
                    return QuerySetProxy(result, self.q)
                return result

            return func
        return attr

    def __iter__(self) -> Iterator[Any]:
        """Return QuerySet and Q objects."""
        return iter([self.__wrapped__, self.q])

    def filter_(self, *args, **kwargs) -> "QuerySetProxy":
        """Replace the `filter` method of the QuerySet class."""
        if len(kwargs) == 0 and len(args) == 1 and isinstance(args[0], models.Q):
            q = args[0]
        else:
            q = models.Q(*args, **kwargs)
        self.q = self.q & q
        return self

    def exclude_(self, *args, **kwargs) -> "QuerySetProxy":
        """Replace the `exclude` method of the QuerySet class."""
        if len(kwargs) == 0 and len(args) == 1 and isinstance(args[0], models.Q):
            q = args[0]
        else:
            q = models.Q(*args, **kwargs)
        self.q = self.q & ~q
        return self


def is_full_text_search_lookup_expr(lookup_expr: str) -> bool:
    """Determine if a lookup_expr is a full text search expression."""
    return lookup_expr.split(LOOKUP_SEP)[-1] == "full_text_search"


def is_regular_lookup_expr(lookup_expr: str) -> bool:
    """Determine whether the lookup_expr must be processed in a regular way."""
    return not any(
        [
            is_full_text_search_lookup_expr(lookup_expr),
        ]
    )


class FilterSetMetaclass(filterset.FilterSetMetaclass):
    def __new__(cls, name, bases, attrs):
        print(f"\n\n\n\n{name}\n///////////////////////////\n")
        print("bases, attrs")
        print(bases)
        print(attrs)

        new_class = super().__new__(cls, name, bases, attrs)

        new_class.related_filters = OrderedDict(
            [
                (name, f)
                for name, f in new_class.declared_filters.items()
                if isinstance(f, filters.BaseRelatedFilter)
            ]
        )

        # See: :meth:`rest_framework_filters.filters.RelatedFilter.bind`
        for f in new_class.related_filters.values():
            f.bind_filterset(new_class)

        # Only expand when model is defined. Model may be undefined for mixins.
        if new_class._meta.model is not None:
            for name, f in new_class.related_filters.items():
                expanded = cls.expand_auto_filter(new_class, name, f)
                new_class.base_filters.update(expanded)

        return new_class

    @classmethod
    def expand_auto_filter(cls, new_class, filter_name, f):
        """Resolve an ``AutoFilter`` into its per-lookup filters.

        This method name is slightly inaccurate since it handles both
        :class:`rest_framework_filters.filters.AutoFilter` and
        :class:`rest_framework_filters.filters.BaseRelatedFilter`, as well as
        their subclasses, which all support per-lookup filter generation.

        Args:
            new_class: The ``FilterSet`` class to generate filters for.
            filter_name: The attribute name of the filter on the ``FilterSet``.
            f: The filter instance.

        Returns:
            A named map of generated filter objects.
        """
        expanded = OrderedDict()

        # get reference to opts/declared filters so originals aren't modified
        orig_meta, orig_declared = new_class._meta, new_class.declared_filters
        new_class._meta = copy.deepcopy(new_class._meta)
        new_class.declared_filters = {}

        # Use meta.fields to generate auto filters
        new_class._meta.fields = {f.field_name: f.lookups or []}
        for gen_name, gen_f in new_class.get_filters().items():
            # get_filters() generates param names from the model field name, so
            # replace the field name with the param name from the filerset
            gen_name = gen_name.replace(f.field_name, filter_name, 1)

            # do not overwrite declared filters
            if gen_name not in orig_declared:
                expanded[gen_name] = gen_f

        # restore reference to opts/declared filters
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
            print("CALL===============: TreeFormMixin>__init__(3)")
            super().__init__(*args, **kwargs)
            self.and_forms = and_forms or []
            self.or_forms = or_forms or []
            self.not_form = not_form

        @property
        def errors(self) -> ErrorDict:
            """Return an ErrorDict for the data provided for the form."""
            print("CALL===============: TreeFormMixin>errors()")
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
        """Return a django Form class suitable of validating the filterset data.
        The form must be tree-like because the data is tree-like.
        """
        print("CALL===============: get_form_class()")
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
        print("CALL===============: form()")
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
        print("CALL===============: create_form(2)")
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
            if data.get("not", None)
            else None,
        )

    def find_filter(self, data_key: str) -> Filter:
        """Find a filter using a data key.

        The data key may differ from a filter name, because
        the data keys may contain DEFAULT_LOOKUP_EXPR and user can create
        a AdvancedFilterSet class without following the naming convention.
        """
        print("CALL===============: find_filter(1)")
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
        print("CALL===============: filter_queryset(1)")
        qs, q = self.get_queryset_proxy_for_form(queryset, self.form)
        # rest_framework_filters/filterset.py:318
        return qs.filter(q)

    def get_queryset_proxy_for_form(
        self,
        queryset: models.QuerySet,
        form: Union[Form, TreeFormMixin],
    ) -> QuerySetProxy:
        """Return a `QuerySetProxy` object for a form's `cleaned_data`."""
        print("CALL===============: get_queryset_proxy_for_form(2)")
        qs = queryset
        q = models.Q()
        for name, value in form.cleaned_data.items():
            # print("name, value")
            # print(name, value)
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
        print("CALL===============: get_filters()")
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
        print("CALL===============: create_full_text_search_filters(1)")
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
        print("CALL===============: create_special_filters(3)")
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
        print("CALL===============: get_fields()")
        return cls._get_fields(is_regular_lookup_expr)

    @classmethod
    def get_full_text_search_fields(cls) -> OrderedDict:
        print("CALL===============: get_full_text_search_fields()")
        """Resolve the `Meta.fields` argument including only full text search lookups."""
        return cls._get_fields(is_full_text_search_lookup_expr)

    @classmethod
    def _get_fields(cls, predicate: Callable[[str], bool]) -> OrderedDict:
        """Resolve the `Meta.fields` argument including lookups that match the predicate."""
        print("CALL===============: _get_fields(1)")

        # if cls.__name__ == "GrapheneHouseFilter":

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
