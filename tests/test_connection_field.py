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
        fields = "__all__"
        interfaces = (graphene.Node,)
        filterset_class = ConnFilterSet


def test_connection_field_no_warning_without_prefix_kwarg(recwarn):
    """Under class-based naming no prefix kwarg is needed; no DeprecationWarning fires.

    Replaces the previous ``test_connection_field_auto_derives_prefix_without_warning``
    which asserted on the removed ``filter_input_type_prefix`` property.
    See ``docs/spec-base_type_naming.md``.
    """
    AdvancedDjangoFilterConnectionField(ConnNode, filterset_class=ConnFilterSet)
    prefix_warnings = [w for w in recwarn.list if "filter_input_type_prefix" in str(w.message)]
    assert not prefix_warnings, "No DeprecationWarning should fire when the kwarg is omitted"


def test_connection_field_custom_prefix_kwarg_is_deprecated():
    """Passing the legacy ``filter_input_type_prefix`` kwarg emits DeprecationWarning.

    The value is ignored under class-based naming — the GraphQL type name derives
    from ``filterset_class.type_name_for()`` regardless of what the caller passes.
    """
    with pytest.warns(DeprecationWarning, match="filter_input_type_prefix"):
        field = AdvancedDjangoFilterConnectionField(
            ConnNode, filterset_class=ConnFilterSet, filter_input_type_prefix="Custom"
        )
    # The emitted type name is derived from the FilterSet class, not the ignored prefix.
    expected = ConnFilterSet.type_name_for()
    assert field.filtering_args["filter"].type.__name__ == expected
    assert expected == "ConnFilterSetInputType"


def test_connection_field_filter_input_type_name_is_class_based():
    """The generated filter input type name derives from the FilterSet class, not the node.

    Replaces the previous ``test_connection_field_default_prefix_no_filterset``.  The spec
    (``docs/spec-base_type_naming.md``) mandates class-based naming: every FilterSet maps
    to a stable type name regardless of which node/connection reaches it.
    """
    field = AdvancedDjangoFilterConnectionField(ConnNode, filterset_class=ConnFilterSet)
    advanced_arg_type = field.filtering_args["filter"].type
    # The root input type's name is ``{FilterSetClass.__name__}InputType`` — no node prefix.
    assert advanced_arg_type.__name__ == ConnFilterSet.type_name_for()
    assert "ConnNode" not in advanced_arg_type.__name__


def test_connection_field_filter_input_type_is_reused_across_fields():
    """Two connection fields bound to the same FilterSet share the same root input type.

    This is the core Apollo cache dedup benefit of class-based naming: no matter which
    connection path reaches a FilterSet, the emitted GraphQL type is the same object.
    """
    field_a = AdvancedDjangoFilterConnectionField(ConnNode, filterset_class=ConnFilterSet)
    field_b = AdvancedDjangoFilterConnectionField(ConnNode, filterset_class=ConnFilterSet)
    assert field_a.filtering_args["filter"].type is field_b.filtering_args["filter"].type


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
    with (
        patch(
            "graphene_django.filter.DjangoFilterConnectionField.resolve_queryset",
            return_value=ConnModel.objects.none(),
        ) as mock_super_resolve,
        patch(
            "django_graphene_filters.connection_field.tree_input_type_to_data",
            return_value={},
        ),
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


def test_invalid_filterset_class_raises_type_error():
    """Passing a non-AdvancedFilterSet filterset_class raises TypeError."""
    from django_filters import FilterSet

    class PlainFilterSet(FilterSet):
        class Meta:
            model = ConnModel
            fields = ["name"]

    with pytest.raises(TypeError, match="AdvancedFilterSet"):
        AdvancedDjangoFilterConnectionField(ConnNode, filterset_class=PlainFilterSet)


def test_map_arguments_to_filters():
    field = AdvancedDjangoFilterConnectionField(ConnNode)
    args = {"name": "foo"}
    filtering_args = {"name": MagicMock()}
    res = field.map_arguments_to_filters(args, filtering_args)
    assert res == {"name": "foo"}

    # Test skipping unknown args
    res2 = field.map_arguments_to_filters({"unknown": "bar"}, filtering_args)
    assert "unknown" not in res2
