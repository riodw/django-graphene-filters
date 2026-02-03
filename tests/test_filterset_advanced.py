from django.db import models
import warnings
from django_graphene_filters.filterset import AdvancedFilterSet, QuerySetProxy, FilterSetMetaclass
from django.db.models import Q
from django import forms
from collections import OrderedDict
from django_filters import Filter
from unittest.mock import MagicMock, patch

class FilterSetTestModel(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()

    class Meta:
        app_label = 'recipes' # use existing app

class SimpleFilterSet(AdvancedFilterSet):
    class Meta:
        model = FilterSetTestModel
        fields = ['name']

def test_queryset_proxy_getattr_non_callable():
    qs = FilterSetTestModel.objects.none()
    proxy = QuerySetProxy(qs)
    # model is a property/attribute, not a callable method on QuerySet
    assert proxy.model == FilterSetTestModel

def test_queryset_proxy_iterator():
    # We need to mock the wrapped object to return something when iterated
    qs = MagicMock(spec=models.QuerySet)
    qs.__iter__.return_value = [FilterSetTestModel(name="A"), FilterSetTestModel(name="B")]
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
            fields = ['name']

    fs = MyFS(data={'name': 'test'}, queryset=FilterSetTestModel.objects.none())
    form = fs.form
    assert form.is_valid()
    assert form.cleaned_data['name'] == 'test'

def test_get_queryset_proxy_for_form_complex():
    class MyFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']

    fs = MyFS(queryset=FilterSetTestModel.objects.none())
    
    # Mock a form with and_forms/or_forms
    class MockForm:
        cleaned_data = {'name': 'test'}
        and_forms = []
        or_forms = []
        not_form = None

    proxy = fs.get_queryset_proxy_for_form(FilterSetTestModel.objects.all(), MockForm())
    assert isinstance(proxy, QuerySetProxy)
    # django-filter often adds __exact
    assert 'name' in str(proxy.q) and 'test' in str(proxy.q)

def test_find_filter_fallback():
    class MyFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']
    
    fs = MyFS(queryset=FilterSetTestModel.objects.none())
    # find_filter should fall back to looking up in filters.values()
    f = fs.find_filter("name")
    assert f.field_name == "name"

def test_construct_search_with_prefix():
    class MyFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']
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

def test_get_filters_with_auto_filter():
    from django_graphene_filters.filters import AutoFilter
    class AutoFS(AdvancedFilterSet):
        name = AutoFilter(lookups=['exact'])
        class Meta:
            model = FilterSetTestModel
            fields = []
            
    filters_dict = AutoFS.get_filters()
    assert 'name' in filters_dict

def test_advanced_filter_set_unbound_form():
    class UnboundFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']
    
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
            fields = {'name': ['full_text_search']}
            
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

    with patch("django_filters.filterset.BaseFilterSet.get_fields", return_value={'name': ['scalar']}):
         res = FallbackFS.get_fields()
         assert 'name' in res
         assert res['name'] == ['scalar']

def test_get_fields_empty_lookups():
    class EmptyLookupsFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']
            
    res = EmptyLookupsFS.get_fields()
    assert 'name' in res

def test_expand_auto_filter_exception():
    mock_f = MagicMock(spec=Filter)
    mock_f.field_name = 'name'
    mock_f.lookups = ['exact']
    with patch("django_filters.filterset.BaseFilterSet.get_filters", side_effect=TypeError):
        res = FilterSetMetaclass.expand_auto_filter(SimpleFilterSet, 'bad', mock_f)
        assert res == {}

def test_metaclass_filter_fields_already_fields():
    class BothFieldsFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']
            filter_fields = ['description']
    assert BothFieldsFS._meta.fields == ['name']

def test_find_filter_loop_fallback_v2():
    class CustomFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']
            
    fs = CustomFS(queryset=FilterSetTestModel.objects.none())
    f = fs.filters.pop('name')
    fs.filters['other_key'] = f
    res = fs.find_filter('name')
    assert res == f

def test_get_queryset_proxy_for_form_all_logic():
    class LogicFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']
            
    fs = LogicFS(queryset=FilterSetTestModel.objects.none())
    
    class MockForm:
        cleaned_data = {}
        def __init__(self, and_forms=None, or_forms=None, not_form=None):
            self.and_forms = and_forms or []
            self.or_forms = or_forms or []
            self.not_form = not_form

    f1 = MockForm()
    f1.cleaned_data = {'name': 'and_val'}
    f2 = MockForm()
    f2.cleaned_data = {'name': 'or_val'}
    f3 = MockForm()
    f3.cleaned_data = {'name': 'not_val'}
    
    main_form = MockForm(and_forms=[f1], or_forms=[f2], not_form=f3)
    
    def mock_find(name):
        m = MagicMock()
        m.filter.return_value = (None, Q(**{f"name": "val"}))
        return m
    fs.find_filter = mock_find
    
    proxy = fs.get_queryset_proxy_for_form(FilterSetTestModel.objects.none(), main_form)
    assert isinstance(proxy, QuerySetProxy)

def test_get_fields_standard_fallback():
    from django_filters import FilterSet as DjangoFS
    class StandardFS(DjangoFS):
        class Meta:
            model = FilterSetTestModel
            fields = ['name']
            
    from django_graphene_filters.filters import RelatedFilter
    class HostFS(AdvancedFilterSet):
        standard = RelatedFilter(StandardFS)
        class Meta:
            model = FilterSetTestModel
            fields = []
            
    fields = HostFS.get_fields()
    assert 'standard__name' in fields

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
    assert 'name' in errs['and']['and_0']

def test_full_text_search_warnings():
    # Hit line 622
    mock_settings = MagicMock()
    mock_settings.IS_POSTGRESQL = False
    
    class FTSFS(AdvancedFilterSet):
        class Meta:
            model = FilterSetTestModel
            fields = {'name': ['full_text_search']}
            
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
            fields = {'name': ['full_text_search']}
            
    with patch("django_graphene_filters.filterset.settings", mock_settings):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            TrigramWarnFS.create_full_text_search_filters(OrderedDict())
            assert len(w) > 0
            assert "Trigram search is not available" in str(w[-1].message)
