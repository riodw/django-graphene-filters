from unittest.mock import MagicMock, patch

import graphene
import pytest
from django.core.exceptions import ValidationError
from django.db import models
from graphene_django import DjangoObjectType

from django_graphene_filters.connection_field import AdvancedDjangoFilterConnectionField
from django_graphene_filters.filterset import AdvancedFilterSet


class ConnModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "recipes"


class ConnFilterSet(AdvancedFilterSet):
    class Meta:
        model = ConnModel
        fields = ["name"]


class ConnNode(DjangoObjectType):
    class Meta:
        model = ConnModel
        interfaces = (graphene.Node,)
        filterset_class = ConnFilterSet


def test_connection_field_prefix_warning():
    with pytest.warns(UserWarning, match="without `filter_input_type_prefix`"):
        AdvancedDjangoFilterConnectionField(ConnNode, filterset_class=ConnFilterSet)


def test_connection_field_custom_prefix():
    field = AdvancedDjangoFilterConnectionField(
        ConnNode, filterset_class=ConnFilterSet, filter_input_type_prefix="Custom"
    )
    assert field.filter_input_type_prefix == "Custom"


def test_connection_field_default_prefix_no_filterset():
    field = AdvancedDjangoFilterConnectionField(ConnNode)
    # node_type.__name__ is 'ConnNode', replaced 'Type' with '' -> 'Node' No wait.
    # ConnNode.replace('Type', '') -> 'ConnNode'
    assert "ConnNode" in field.filter_input_type_prefix


def test_connection_field_extra_meta():
    field = AdvancedDjangoFilterConnectionField(ConnNode, extra_filter_meta={"some": "meta"})
    # This will trigger filterset_class property which uses extra_filter_meta
    fs_class = field.filterset_class
    assert fs_class is not None


def test_resolve_queryset_invalid_form():
    field = AdvancedDjangoFilterConnectionField(ConnNode, filterset_class=ConnFilterSet)
    info = MagicMock()
    info.context = None

    # Mocking filterset to have errors
    mock_fs = MagicMock()
    mock_fs.form.is_valid.return_value = False
    mock_fs.form.errors.as_json.return_value = '{"error": "msg"}'

    # Mock resolve_queryset to avoid complex super calls
    mock_connection = MagicMock()
    with patch(
        "graphene_django.filter.DjangoFilterConnectionField.resolve_queryset",
        return_value=ConnModel.objects.none(),
    ) as mock_super_resolve, patch(
        "django_graphene_filters.connection_field.tree_input_type_to_data",
        return_value={},
    ):

        # We need mock_super_resolve to NOT call the actual super, but wait,
        # I'm already patching it! So it won't call the actual one.
        # But wait, AdvancedDjangoFilterConnectionField.resolve_queryset calls:
        # super(DjangoFilterConnectionField, cls).resolve_queryset(...)
        # which is NOT the one I patched (I patched DjangoFilterConnectionField.resolve_queryset).

        with pytest.raises(ValidationError) as exc:
            factory = MagicMock(return_value=mock_fs)
            field.resolve_queryset(mock_connection, ConnModel.objects.none(), info, {}, {}, factory)
        assert '{"error": "msg"}' in str(exc.value)


def test_map_arguments_to_filters():
    field = AdvancedDjangoFilterConnectionField(ConnNode)
    args = {"name": "foo"}
    filtering_args = {"name": MagicMock()}
    res = field.map_arguments_to_filters(args, filtering_args)
    assert res == {"name": "foo"}

    # Test skipping unknown args
    res2 = field.map_arguments_to_filters({"unknown": "bar"}, filtering_args)
    assert "unknown" not in res2
