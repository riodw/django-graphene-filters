import warnings
from collections import OrderedDict
from unittest.mock import MagicMock, patch

from django import forms
from django.db import models
from django.db.models import Q
from django_filters import Filter

from django_graphene_filters.filterset import (
    AdvancedFilterSet,
    FilterSetMetaclass,
    QuerySetProxy,
)


class FilterSetTestModel(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()

    class Meta:
        app_label = "recipes"  # use existing app


class SimpleFilterSet(AdvancedFilterSet):
    class Meta:
        model = FilterSetTestModel
        fields = ["name"]


def test_queryset_proxy_getattr_non_callable():
    qs = FilterSetTestModel.objects.none()
    proxy = QuerySetProxy(qs)
    # model is a property/attribute, not a callable method on QuerySet
    assert proxy.model == FilterSetTestModel


def test_queryset_proxy_iterator():
    # We need to mock the wrapped object to return something when iterated
    qs = MagicMock(spec=models.QuerySet)
    qs.__iter__.return_value = [
        FilterSetTestModel(name="A"),
        FilterSetTestModel(name="B"),
    ]
    proxy = QuerySetProxy(qs)
    items = list(proxy)
    assert len(items) == 2


def test_tree_form_mixin_not_errors():
    class MyForm(AdvancedFilterSet.TreeFormMixin, forms.Form):
        pass

    f = MyForm(data={})
    # just checking it doesn't crash
    assert f.not_form is None


def test_create_form_full():
    class MyFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    fs = MyFS(data={"name": "test"}, queryset=FilterSetTestModel.objects.none())
    form = fs.form
    assert form.is_valid()
    assert form.cleaned_data["name"] == "test"


def test_get_queryset_proxy_for_form_complex():
    class MyFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    fs = MyFS(queryset=FilterSetTestModel.objects.none())

    # Mock a form with and_forms/or_forms
    class MockForm:
        cleaned_data = {"name": "test"}
        and_forms = []
        or_forms = []
        not_form = None

    proxy = fs.get_queryset_proxy_for_form(FilterSetTestModel.objects.all(), MockForm())
    assert isinstance(proxy, QuerySetProxy)
    # django-filter often adds __exact
    assert "name" in str(proxy.q) and "test" in str(proxy.q)


def test_find_filter_fallback():
    class MyFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    fs = MyFS(queryset=FilterSetTestModel.objects.none())
    # find_filter should fall back to looking up in filters.values()
    f = fs.find_filter("name")
    assert f.field_name == "name"


def test_construct_search_with_prefix():
    class MyFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]
            filter_input_type_prefix = "MyPrefix"

    fs = MyFS(queryset=FilterSetTestModel.objects.none())
    # This hits internal logic of construct_search
    res = fs.construct_search("name")
    assert res == "name__icontains"


def test_queryset_proxy_make_callable_proxy_returns_qs():
    qs = FilterSetTestModel.objects.none()
    proxy = QuerySetProxy(qs)
    res = proxy.all()
    assert isinstance(res, QuerySetProxy)


def test_queryset_proxy_filter_q_arg():
    qs = FilterSetTestModel.objects.none()
    proxy = QuerySetProxy(qs)
    q = Q(name="test")
    res = proxy.filter(q)
    assert res.q == q


def test_queryset_proxy_exclude_q_arg():
    qs = FilterSetTestModel.objects.none()
    proxy = QuerySetProxy(qs)
    q = Q(name="test")
    res = proxy.exclude(q)
    assert res.q == ~q


def test_queryset_proxy_exclude_kwargs():
    qs = FilterSetTestModel.objects.none()
    proxy = QuerySetProxy(qs)
    res = proxy.exclude(name="test")
    assert res.q == ~Q(name="test")


def test_expand_related_filter_no_target():
    rf = MagicMock()
    rf.filterset = None
    res = FilterSetMetaclass.expand_related_filter(None, "name", rf)
    assert res == {}


def test_get_filters_cache_hit():
    class CacheFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = []

    CacheFS._expanded_filters = {"foo": "bar"}
    assert CacheFS.get_filters() == {"foo": "bar"}


def test_get_filters_cache_written_after_first_call():
    """Regression: _expanded_filters must be populated after the first get_filters() call.

    On slow servers (1 vCPU) the first request expanded every RelatedFilter from
    scratch on every call because the cache was never written.  The fix writes the
    result to cls._expanded_filters so subsequent calls return immediately.

    This test verifies three invariants:
    1. The cache is absent before the first explicit call (the metaclass must NOT
       pre-populate it, since it runs before related_filters is set on the class).
    2. The cache is populated after the first call completes.
    3. Subsequent calls hit the cache: the underlying super().get_filters() is called
       exactly once regardless of how many times get_filters() is invoked.
    """
    import django_filters.filterset as base_module

    class OnceFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    # 1. Cache absent before any explicit call
    assert getattr(OnceFS, "_expanded_filters", None) is None

    call_count = 0
    original = base_module.BaseFilterSet.get_filters.__func__

    def counting_get_filters(cls):
        nonlocal call_count
        call_count += 1
        return original(cls)

    with patch.object(base_module.BaseFilterSet, "get_filters", classmethod(counting_get_filters)):
        first_result = OnceFS.get_filters()
        second_result = OnceFS.get_filters()
        third_result = OnceFS.get_filters()

    # 2. Cache written after first call
    assert OnceFS._expanded_filters is not None

    # 3. super().get_filters() called only once — subsequent calls served from cache
    assert call_count == 1, f"Expected 1 super call, got {call_count}"

    # All three results are the identical cached object
    assert first_result is second_result is third_result


def test_get_filters_with_auto_filter():
    from django_graphene_filters.filters import AutoFilter

    class AutoFS(AdvancedFilterSet):
        name = AutoFilter(lookups=["exact"])

        class Meta:
            model = FilterSetTestModel
            fields = []

    filters_dict = AutoFS.get_filters()
    assert "name" in filters_dict


def test_advanced_filter_set_unbound_form():
    class UnboundFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    fs = UnboundFS(queryset=FilterSetTestModel.objects.none())
    form = fs.form
    assert not form.is_bound


def test_related_filter_callable_filterset():
    from django_graphene_filters.filters import RelatedFilter

    mock_fs_class = MagicMock()
    rf = RelatedFilter(filterset=lambda: mock_fs_class)
    assert rf.filterset == mock_fs_class


def test_create_full_text_search_filters_postgres():
    mock_settings = MagicMock()
    mock_settings.IS_POSTGRESQL = True
    mock_settings.HAS_TRIGRAM_EXTENSION = True

    class TrigramFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["full_text_search"]}

    with patch("django_graphene_filters.filterset.settings", mock_settings):
        res = TrigramFS.create_full_text_search_filters(OrderedDict())
        assert any("search_query" in k for k in res.keys())
        assert any("search_rank" in k for k in res.keys())
        assert any("name__trigram" in k for k in res.keys())


def test_get_fields_fallback_v4():
    class FallbackFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = []

    with patch(
        "django_filters.filterset.BaseFilterSet.get_fields",
        return_value={"name": ["scalar"]},
    ):
        res = FallbackFS.get_fields()
        assert "name" in res
        assert res["name"] == ["scalar"]


def test_get_fields_empty_lookups():
    class EmptyLookupsFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    res = EmptyLookupsFS.get_fields()
    assert "name" in res


def test_expand_auto_filter_exception():
    mock_f = MagicMock(spec=Filter)
    mock_f.field_name = "name"
    mock_f.lookups = ["exact"]
    with patch("django_filters.filterset.BaseFilterSet.get_filters", side_effect=TypeError):
        res = FilterSetMetaclass.expand_auto_filter(SimpleFilterSet, "bad", mock_f)
        assert res == {}


def test_metaclass_filter_fields_already_fields():
    class BothFieldsFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]
            filter_fields = ["description"]

    assert BothFieldsFS._meta.fields == ["name"]


def test_find_filter_loop_fallback_v2():
    class CustomFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    fs = CustomFS(queryset=FilterSetTestModel.objects.none())
    f = fs.filters.pop("name")
    fs.filters["other_key"] = f
    res = fs.find_filter("name")
    assert res == f


def test_get_queryset_proxy_for_form_all_logic():
    class LogicFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    fs = LogicFS(queryset=FilterSetTestModel.objects.none())

    class MockForm:
        cleaned_data = {}

        def __init__(self, and_forms=None, or_forms=None, not_form=None):
            self.and_forms = and_forms or []
            self.or_forms = or_forms or []
            self.not_form = not_form

    f1 = MockForm()
    f1.cleaned_data = {"name": "and_val"}
    f2 = MockForm()
    f2.cleaned_data = {"name": "or_val"}
    f3 = MockForm()
    f3.cleaned_data = {"name": "not_val"}

    main_form = MockForm(and_forms=[f1], or_forms=[f2], not_form=f3)

    def mock_find(name):
        m = MagicMock()
        m.filter.return_value = (None, Q(**{"name": "val"}))
        return m

    fs.find_filter = mock_find

    proxy = fs.get_queryset_proxy_for_form(FilterSetTestModel.objects.none(), main_form)
    assert isinstance(proxy, QuerySetProxy)


def test_get_fields_standard_fallback():
    from django_filters import FilterSet as DjangoFS

    class StandardFS(DjangoFS):
        class Meta:
            model = FilterSetTestModel
            fields = ["name"]

    from django_graphene_filters.filters import RelatedFilter

    class HostFS(AdvancedFilterSet):
        standard = RelatedFilter(StandardFS)

        class Meta:
            model = FilterSetTestModel
            fields = []

    fields = HostFS.get_fields()
    assert "standard__name" in fields


def test_build_search_conditions_empty():
    fs = SimpleFilterSet(queryset=FilterSetTestModel.objects.none())
    res = fs.build_search_conditions(FilterSetTestModel.objects.none(), "query")
    assert res.count() == 0


def test_build_search_conditions_no_query():
    fs = SimpleFilterSet(queryset=FilterSetTestModel.objects.none())
    res = fs.build_search_conditions(FilterSetTestModel.objects.none(), "")
    assert res.count() == 0


def test_tree_form_mixin_errors_nesting():
    class MyForm(AdvancedFilterSet.TreeFormMixin, forms.Form):
        pass

    class InnerForm(forms.Form):
        name = forms.CharField()

    inner = InnerForm(data={})
    inner.is_valid()

    f = MyForm()
    f.and_forms = [inner]
    f.or_forms = []

    errs = f.errors
    assert "name" in errs["and"]["and_0"]


def test_full_text_search_warnings():
    # Hit line 622
    mock_settings = MagicMock()
    mock_settings.IS_POSTGRESQL = False

    class FTSFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["full_text_search"]}

    with patch("django_graphene_filters.filterset.settings", mock_settings):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            FTSFS.create_full_text_search_filters(OrderedDict())
            assert len(w) > 0
            assert "Full text search is not available" in str(w[-1].message)


def test_trigram_search_warnings():
    # Hit line 637
    mock_settings = MagicMock()
    mock_settings.IS_POSTGRESQL = True
    mock_settings.HAS_TRIGRAM_EXTENSION = False

    class TrigramWarnFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["full_text_search"]}

    with patch("django_graphene_filters.filterset.settings", mock_settings):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            TrigramWarnFS.create_full_text_search_filters(OrderedDict())
            assert len(w) > 0
            assert "Trigram search is not available" in str(w[-1].message)


# ---------------------------------------------------------------------------
# Regression: RelatedFilter expansion must sync base_filters
# ---------------------------------------------------------------------------


class RelatedTestModel(models.Model):
    """Target model for RelatedFilter regression tests."""

    title = models.CharField(max_length=100)
    parent = models.ForeignKey(
        FilterSetTestModel,
        related_name="children",
        on_delete=models.CASCADE,
    )

    class Meta:
        app_label = "recipes"


def test_related_filter_expansion_syncs_base_filters():
    """Expanded RelatedFilter paths must appear in base_filters.

    Before the fix, base_filters only contained Meta.fields entries.
    RelatedFilter paths (e.g. ``children__title``) were in the GraphQL
    schema but silently dropped during actual ORM filtering.
    """
    from django_graphene_filters.filters import RelatedFilter

    class ChildFilter(AdvancedFilterSet):
        class Meta:
            model = RelatedTestModel
            fields = {"title": ["exact", "icontains"]}

    class ParentFilter(AdvancedFilterSet):
        children = RelatedFilter(ChildFilter, field_name="children")

        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["exact"]}

    # Trigger expansion
    all_filters = ParentFilter.get_filters()

    # Expanded path must be in get_filters() result
    assert "children__title" in all_filters, (
        f"Expanded path 'children__title' missing from get_filters(). Keys: {list(all_filters.keys())}"
    )

    # And critically — also in base_filters (used by forms / filter_queryset)
    assert "children__title" in ParentFilter.base_filters, (
        f"Expanded path 'children__title' missing from base_filters. "
        f"Keys: {list(ParentFilter.base_filters.keys())}. "
        "This means the filter is visible in the schema but silently ignored at runtime."
    )


def test_related_filter_expanded_paths_reach_form():
    """A filterset instance's form must include fields for RelatedFilter paths.

    This is the consequence of base_filters being synced: when a filterset
    is instantiated, ``self.filters = deepcopy(base_filters)``, and the
    form is built from ``self.filters``.  If base_filters lacks the
    expanded paths, the form silently ignores them in cleaned_data.
    """
    from django_graphene_filters.filters import RelatedFilter

    class ChildFilter2(AdvancedFilterSet):
        class Meta:
            model = RelatedTestModel
            fields = {"title": ["exact"]}

    class ParentFilter2(AdvancedFilterSet):
        children = RelatedFilter(ChildFilter2, field_name="children")

        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["exact"]}

    # Force expansion
    ParentFilter2.get_filters()

    # Create an instance with data that uses the expanded path
    fs = ParentFilter2(
        data={"children__title": "hello"},
        queryset=FilterSetTestModel.objects.none(),
    )

    assert fs.form.is_valid()
    assert "children__title" in fs.form.cleaned_data, (
        f"Expanded path 'children__title' not in form cleaned_data. "
        f"Keys: {list(fs.form.cleaned_data.keys())}. "
        "The filter data will be silently dropped."
    )


# ---------------------------------------------------------------------------
# Regression: ``_expanded_filters`` cache must be per-class, not inherited.
#
# A previous implementation read the cache via ``getattr(cls, ...)`` which
# walks the MRO — a subclass of a FilterSet whose parent had already been
# expanded would silently return the parent's cached dict and skip its own
# expansion.  The fix reads from ``cls.__dict__`` so each class caches
# independently.
# ---------------------------------------------------------------------------


def test_subclass_does_not_inherit_parent_expanded_filters_cache():
    """A subclass must run its own expansion, not return the parent's cache."""
    from django_graphene_filters.filters import RelatedFilter

    class ChildFS(AdvancedFilterSet):
        class Meta:
            model = RelatedTestModel
            fields = {"title": ["exact"]}

    class ParentFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["exact"]}

    # Prime the parent cache.
    parent_filters = ParentFS.get_filters()
    assert ParentFS.__dict__.get("_expanded_filters") is parent_filters

    class SubFS(ParentFS):
        # Add a RelatedFilter that the parent does NOT have.  If the
        # subclass mistakenly inherits the parent's cache, this expanded
        # path will be missing from the result.
        children = RelatedFilter(ChildFS, field_name="children")

        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["exact"]}

    # Before SubFS's own get_filters() runs, its __dict__ must NOT carry
    # the parent's cache.
    assert "_expanded_filters" not in SubFS.__dict__

    sub_filters = SubFS.get_filters()

    # The subclass's expanded set must include its own RelatedFilter paths.
    assert "children__title" in sub_filters, (
        f"Subclass expansion leaked parent's cache: expected 'children__title' in {list(sub_filters.keys())}."
    )
    # And the two caches must be distinct objects — the subclass owns its own.
    assert SubFS.__dict__["_expanded_filters"] is sub_filters
    assert ParentFS.__dict__["_expanded_filters"] is not sub_filters


def test_sibling_subclasses_have_independent_caches():
    """Two siblings of the same parent cache independently of each other."""
    from django_graphene_filters.filters import RelatedFilter

    class ChildA(AdvancedFilterSet):
        class Meta:
            model = RelatedTestModel
            fields = {"title": ["exact"]}

    class ChildB(AdvancedFilterSet):
        class Meta:
            model = RelatedTestModel
            fields = {"title": ["icontains"]}

    class ParentBase(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["exact"]}

    class SubA(ParentBase):
        children = RelatedFilter(ChildA, field_name="children")

        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["exact"]}

    class SubB(ParentBase):
        children = RelatedFilter(ChildB, field_name="children")

        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["exact"]}

    filters_a = SubA.get_filters()
    filters_b = SubB.get_filters()

    # Each sibling must reach its own child filterset's lookup set —
    # ChildA only has 'exact', ChildB only has 'icontains'.
    assert "children__title" in filters_a
    assert "children__title__icontains" not in filters_a

    assert "children__title__icontains" in filters_b
    # Under the pre-fix MRO-leak behaviour, SubB would reuse SubA's
    # cache (or vice versa) if expansion order happened to matter.
    assert SubA.__dict__["_expanded_filters"] is not SubB.__dict__["_expanded_filters"]


def test_fresh_subclass_after_parent_expansion_still_expands():
    """Defining a subclass AFTER the parent has been expanded still triggers expansion."""

    class ParentCached(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = {"name": ["exact", "icontains"]}

    # Prime the parent cache.
    ParentCached.get_filters()
    assert ParentCached.__dict__.get("_expanded_filters") is not None

    class LateSub(ParentCached):
        class Meta:
            model = FilterSetTestModel
            # Different field set than parent.
            fields = {"description": ["exact"]}

    # The subclass must expand its own Meta.fields, not reuse the parent's.
    sub_filters = LateSub.get_filters()
    assert "description" in sub_filters, (
        f"LateSub expansion leaked parent's 'name' filters instead of its own "
        f"'description'.  Keys: {list(sub_filters.keys())}"
    )
