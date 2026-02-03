import pytest
import graphene
from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory
from django_graphene_filters.filterset import AdvancedFilterSet
from django_graphene_filters.filters import TrigramFilter
from django.db import models
from unittest.mock import MagicMock, patch

class FactModel(models.Model):
    name = models.CharField(max_length=100)
    class Meta:
        app_label = 'recipes'

class FactFilterSet(AdvancedFilterSet):
    class Meta:
        model = FactModel
        fields = ['name']

def test_factory_special_filter():
    # We want to trigger line 148: if root.name in self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES:
    # Roots come from filterset_to_trees.
    # We need a filter where field_name starts with a special postfix.
    from django_graphene_filters.filters import SearchQueryFilter
    
    class SpecialFS(AdvancedFilterSet):
        search = SearchQueryFilter()
        class Meta:
            model = FactModel
            fields = []
            
    factory = FilterArgumentsFactory(SpecialFS, "Special")
    args = factory.arguments
    assert 'filter' in args

def test_create_input_object_type_cache():
    # Call twice to hit line 188
    FilterArgumentsFactory.input_object_types = {} # Reset
    t1 = FilterArgumentsFactory.create_input_object_type("CachedType", {"f": graphene.String()})
    t2 = FilterArgumentsFactory.create_input_object_type("CachedType", {"f": graphene.String()})
    assert t1 is t2

def test_get_field_model_formfield():
    factory = FilterArgumentsFactory(FactFilterSet, "Fact")
    f_obj = MagicMock()
    f_obj.lookup_expr = "exact"
    f_obj.field_name = "name"
    f_obj.extra = {}
    f_obj.field = MagicMock() # original field
    
    with patch("django_graphene_filters.filter_arguments_factory.get_model_field") as mock_get_field, \
         patch("django_graphene_filters.filter_arguments_factory.convert_form_field") as mock_convert:
        
        mock_model_field = MagicMock()
        mock_get_field.return_value = mock_model_field
        mock_convert.return_value = MagicMock()
        
        factory.get_field("name", f_obj)
        assert mock_model_field.formfield.called
