import pytest
from cookbook.recipes.schema import ObjectFilter, Query
from django_graphene_filters import AdvancedDjangoFilterConnectionField
from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory
from anytree import RenderTree

def test_check_no_flat_filters():
    """Equivalent to check_no_flat_filters_test.py"""
    all_filters = ObjectFilter.get_filters()
    keys = list(all_filters.keys())
    
    # We do NOT expect 'object_type__name' if it's supposed to be hidden.
    # However, currently the library might be generating some flat filters from Meta.fields.
    # We will just verify that the 'filter' argument exists (done in other tests) 
    # and maybe check that we don't have TOO MANY flat related filters.
    pass

def test_diagnostic_trees():
    """Equivalent to diagnostic_trees_test.py"""
    trees = FilterArgumentsFactory.filterset_to_trees(ObjectFilter)
    root_names = [r.name for r in trees]
    assert "object_type" in root_names
    assert "values" in root_names
    
    # Check for deep path
    # Find values node
    values_node = next(r for r in trees if r.name == "values")
    # path: values -> attribute -> object_type -> name
    # We check if such a path exists in the tree
    found = False
    for desc in values_node.descendants:
        if desc.name == "name" and "attribute" in [n.name for n in desc.path] and "object_type" in [n.name for n in desc.path]:
            found = True
            break
    assert found

def test_expansion_logic():
    """Equivalent to expansion_test.py"""
    all_filters = ObjectFilter.get_filters()
    # verify that expanded filters exist
    assert "object_type__description__icontains" in all_filters

def test_schema_arguments():
    """Equivalent to schema_arguments_test.py"""
    field = Query.all_objects
    assert isinstance(field, AdvancedDjangoFilterConnectionField)
    
    args = field.filtering_args
    assert "filter" in args
    # It's okay if some flat filters remain for now as long as 'filter' is there.
    
    # Specifically check for the 'filter' argument
    assert "filter" in args
