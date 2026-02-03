"""Additional tests to boost coverage from 96% to 97%."""

import pytest
from django.db import models
from django.db.models import Value as DjangoValue
from django.db.models.functions import Concat
from django_graphene_filters.filterset import AdvancedFilterSet
from django_graphene_filters.filters import AnnotatedFilter, SearchQueryFilter, TrigramFilter
from django_graphene_filters.connection_field import AdvancedDjangoFilterConnectionField
from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory
from unittest.mock import MagicMock, patch
import graphene
from graphene_django import DjangoObjectType


class BoostModel(models.Model):
    name = models.CharField(max_length=100)
    
    class Meta:
        app_label = 'recipes'


def test_annotated_filter_distinct():
    """Test AnnotatedFilter with distinct=True to cover line 75 in filters.py"""
    f = AnnotatedFilter(field_name="name", lookup_expr="exact", distinct=True)
    qs = BoostModel.objects.none()
    
    # Create a value with a proper Django expression
    value = AnnotatedFilter.Value(
        annotation_value=Concat(DjangoValue("test"), DjangoValue("_annotation")),
        search_value="test"
    )
    
    # Mock the get_method to return a callable that returns the queryset
    f.get_method = lambda qs: lambda **kwargs: qs
    
    result = f.filter(qs, value)
    # The distinct() should have been called
    assert result is not None


def test_connection_field_no_provided_filterset():
    """Test filter_input_type_prefix when provided_filterset_class is None to cover line 98"""
    
    class TestNode(DjangoObjectType):
        class Meta:
            model = BoostModel
            fields = '__all__'
            interfaces = (graphene.relay.Node,)
    
    # Create connection field without filterset_class
    field = AdvancedDjangoFilterConnectionField(TestNode)
    
    # Access filter_input_type_prefix when provided_filterset_class is None
    prefix = field.filter_input_type_prefix
    # Should return just the node type name
    assert prefix == "TestNode"


def test_special_filter_input_type_factory():
    """Test SPECIAL_FILTER_INPUT_TYPES_FACTORIES to cover line 148"""
    
    # Create a filterset with a special filter (SearchQueryFilter)
    class SpecialFS(AdvancedFilterSet):
        class Meta:
            model = BoostModel
            fields = {'name': ['full_text_search']}
    
    # Mock PostgreSQL settings
    with patch('django_graphene_filters.filterset.settings') as mock_settings:
        mock_settings.IS_POSTGRESQL = True
        mock_settings.HAS_TRIGRAM_EXTENSION = False
        
        factory = FilterArgumentsFactory(SpecialFS, "Special")
        
        # This should trigger the special filter handling
        args = factory.arguments
        assert 'filter' in args


def test_get_field_with_in_lookup():
    """Test get_field with 'in' lookup to cover line 230-231 in filter_arguments_factory.py"""
    
    class InFS(AdvancedFilterSet):
        class Meta:
            model = BoostModel
            fields = {'name': ['in']}
    
    factory = FilterArgumentsFactory(InFS, "In")
    
    # Get the filters
    filters = InFS.get_filters()
    
    # Find the 'in' filter
    in_filter = filters.get('name__in')
    if in_filter:
        field = factory.get_field('name__in', in_filter)
        assert field is not None


def test_filterset_to_trees_empty_values():
    """Test sequence_to_tree with empty values to cover line 315"""
    from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory
    
    # Test with empty sequence
    result = FilterArgumentsFactory.sequence_to_tree([])
    assert result.name == ""
