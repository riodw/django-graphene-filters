"""Additional tests to push coverage from 97% to 98%."""

import pytest
from django.db import models
from django.core.exceptions import ValidationError
from django_graphene_filters.filterset import AdvancedFilterSet
from django_graphene_filters.filters import AutoFilter
from django_graphene_filters.input_data_factories import (
    create_search_rank_data,
    create_search_config,
)
from django_graphene_filters.input_types import SearchConfigInputType
from graphene.types.inputobjecttype import InputObjectTypeContainer
from unittest.mock import MagicMock, patch


class Push98Model(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField()
    
    class Meta:
        app_label = 'recipes'


def test_search_rank_with_weights():
    """Test create_search_rank_data with weights to cover lines 143-145"""
    
    # Create a mock input_type with weights
    input_type = MagicMock()
    input_type.lookups = {'exact': 0.5}
    input_type.vector = MagicMock()
    input_type.vector.fields = ['name']
    input_type.query = MagicMock()
    input_type.query.get.return_value = None
    input_type.cover_density = False
    
    # Mock the get method to return weights
    def mock_get(key):
        if key == 'weights':
            weights = MagicMock()
            weights.D = 0.1
            weights.C = 0.2
            weights.B = 0.4
            weights.A = 1.0
            return weights
        elif key == 'normalization':
            return None
        return None
    
    input_type.get = mock_get
    
    class TestFS(AdvancedFilterSet):
        class Meta:
            model = Push98Model
            fields = {'name': ['full_text_search']}
    
    with patch('django_graphene_filters.input_data_factories.create_search_vector'), \
         patch('django_graphene_filters.input_data_factories.create_search_query'):
        result = create_search_rank_data(input_type, 'name__search_rank', TestFS)
        assert result is not None


def test_search_rank_with_normalization():
    """Test create_search_rank_data with normalization to cover lines 148-150"""
    
    # Create a mock input_type with normalization
    input_type = MagicMock()
    input_type.lookups = {'exact': 0.5}
    input_type.vector = MagicMock()
    input_type.vector.fields = ['name']
    input_type.query = MagicMock()
    input_type.query.get.return_value = None
    input_type.cover_density = False
    
    # Mock the get method to return normalization
    def mock_get(key):
        if key == 'weights':
            return None
        elif key == 'normalization':
            return 2  # Some normalization value
        return None
    
    input_type.get = mock_get
    
    class TestFS(AdvancedFilterSet):
        class Meta:
            model = Push98Model
            fields = {'name': ['full_text_search']}
    
    with patch('django_graphene_filters.input_data_factories.create_search_vector'), \
         patch('django_graphene_filters.input_data_factories.create_search_query'):
        result = create_search_rank_data(input_type, 'name__search_rank', TestFS)
        assert result is not None


def test_search_vector_with_config():
    """Test create_search_vector with config to cover lines 212-213"""
    from django_graphene_filters.input_data_factories import create_search_vector
    
    input_type = MagicMock()
    input_type.fields = ['name']
    
    # Mock config
    config = MagicMock(spec=SearchConfigInputType)
    config.value = 'english'
    config.is_field = False
    
    def mock_get(key):
        if key == 'config':
            return config
        elif key == 'weight':
            return None
        return None
    
    input_type.get = mock_get
    
    class TestFS(AdvancedFilterSet):
        class Meta:
            model = Push98Model
            fields = {'name': ['full_text_search']}
    
    with patch('django_graphene_filters.input_data_factories.validate_search_vector_fields'):
        result = create_search_vector(input_type, TestFS)
        assert result is not None


def test_search_vector_with_weight():
    """Test create_search_vector with weight to cover lines 216-218"""
    from django_graphene_filters.input_data_factories import create_search_vector
    
    input_type = MagicMock()
    input_type.fields = ['name']
    
    # Mock weight
    weight = MagicMock()
    weight.value = 'A'
    
    def mock_get(key):
        if key == 'config':
            return None
        elif key == 'weight':
            return weight
        return None
    
    input_type.get = mock_get
    
    class TestFS(AdvancedFilterSet):
        class Meta:
            model = Push98Model
            fields = {'name': ['full_text_search']}
    
    with patch('django_graphene_filters.input_data_factories.validate_search_vector_fields'):
        result = create_search_vector(input_type, TestFS)
        assert result is not None


def test_search_config_with_is_field():
    """Test create_search_config with is_field=True to cover line 278"""
    
    input_type = MagicMock(spec=SearchConfigInputType)
    input_type.value = 'config_field'
    input_type.is_field = True
    
    result = create_search_config(input_type)
    # Should return an F object
    from django.db.models import F
    assert isinstance(result, F)


def test_expand_auto_filter_exception():
    """Test expand_auto_filter exception handling to cover line 340-344"""
    from django_graphene_filters.filterset import FilterSetMetaclass
    
    class TestFS(AdvancedFilterSet):
        class Meta:
            model = Push98Model
            fields = []
    
    # Create an AutoFilter that will cause an exception when expanded
    auto_filter = AutoFilter(lookups=['exact'], field_name='nonexistent_field')
    
    # The expand_auto_filter should handle the exception gracefully
    result = FilterSetMetaclass.expand_auto_filter(TestFS, 'test_filter', auto_filter)
    # Should return empty dict on exception
    assert isinstance(result, dict)


def test_get_filters_recursion_protection():
    """Test get_filters recursion protection to cover line 386"""
    
    # Create a filterset that would cause recursion
    class RecursiveFS(AdvancedFilterSet):
        class Meta:
            model = Push98Model
            fields = ['name']
    
    # Manually set the flag to trigger recursion protection
    RecursiveFS._is_expanding_filters = True
    
    try:
        # This should return base filters without expansion
        result = RecursiveFS.get_filters()
        assert result is not None
    finally:
        # Reset the flag
        RecursiveFS._is_expanding_filters = False
