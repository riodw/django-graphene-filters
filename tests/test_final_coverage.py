from unittest.mock import MagicMock, patch

import graphene
import pytest
from django.db import models
from graphene_django import DjangoObjectType
from graphene_django.types import DjangoObjectTypeOptions

from django_graphene_filters.connection_field import AdvancedDjangoFilterConnectionField
from django_graphene_filters.filters import RelatedFilter
from django_graphene_filters.filterset import AdvancedFilterSet
from django_graphene_filters.mixins import (
    LazyRelatedClassMixin,
)
from django_graphene_filters.object_type import AdvancedDjangoObjectType
from django_graphene_filters.order_arguments_factory import (
    OrderArgumentsFactory,
)
from django_graphene_filters.orders import RelatedOrder
from django_graphene_filters.orderset import AdvancedOrderSet

# ---------------------------------------------------------------------------
# Test Models
# ---------------------------------------------------------------------------


class FinalUniqueCoverageModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "recipes"


# ---------------------------------------------------------------------------
# connection_field.py
# ---------------------------------------------------------------------------


def test_no_ordering_args_when_orderset_absent():
    """When a node type has no orderset, the connection field emits no ``orderBy`` arg.

    Replaces the previous ``test_order_input_type_prefix_no_orderset_branch`` which
    asserted on the removed ``order_input_type_prefix`` property.  Under class-based
    naming (``docs/spec-base_type_naming.md``) there is no prefix surface at all —
    the equivalent observable behaviour is simply whether ``orderBy`` shows up.
    """

    class NodeNoOrder(DjangoObjectType):
        class Meta:
            model = FinalUniqueCoverageModel
            fields = "__all__"
            interfaces = (graphene.relay.Node,)
            filter_fields = ["name"]

    field = AdvancedDjangoFilterConnectionField(NodeNoOrder)
    assert field.provided_orderset_class is None
    assert field.ordering_args == {}
    assert "orderBy" not in field.args


def test_resolve_queryset_with_orderset_application():
    """Test connection_field.py lines 287-288: branch where orderset is applied."""

    class SimpleOS(AdvancedOrderSet):
        class Meta:
            model = FinalUniqueCoverageModel
            fields = ["name"]

    class NodeWithOrder(AdvancedDjangoObjectType):
        class Meta:
            model = FinalUniqueCoverageModel
            fields = "__all__"
            interfaces = (graphene.relay.Node,)
            orderset_class = SimpleOS

    field = AdvancedDjangoFilterConnectionField(NodeWithOrder)
    info = MagicMock()
    info.context = MagicMock()
    qs = FinalUniqueCoverageModel.objects.none()

    # Mocking necessary bits for resolve_queryset
    connection = MagicMock()
    connection._meta.node = NodeWithOrder

    # Filterset mock — filterset.qs returns a mock queryset whose
    # .order_by() and .distinct() chain back to itself.
    filterset = MagicMock()
    filterset.form.is_valid.return_value = True
    mock_qs = MagicMock()
    mock_qs.order_by.return_value = mock_qs
    mock_qs.distinct.return_value = mock_qs
    filterset.qs = mock_qs

    with patch("django_graphene_filters.connection_field.get_filterset_class") as mock_get_fs:
        mock_fs_class = MagicMock(return_value=filterset)
        mock_get_fs.return_value = mock_fs_class

        # Triggering resolve_queryset
        # Need orderset_class and order_arg to be truthy to hit 287-288
        args = {"orderBy": [{"name": "asc"}]}
        field.resolve_queryset(connection, [], info, args, {}, mock_fs_class)

        # The orderset applies .order_by() on the queryset
        assert mock_qs.order_by.called


# ---------------------------------------------------------------------------
# mixins.py
# ---------------------------------------------------------------------------


def test_lazy_related_class_mixin_raise_path_not_provided():
    """Test mixins.py line 31: raise ImportError when bound_class is None."""
    mixin = LazyRelatedClassMixin()
    # Path that doesn't exist to trigger ImportError
    with pytest.raises(ImportError):
        mixin.resolve_lazy_class("missing.path.Class", None)


# ---------------------------------------------------------------------------
# object_type.py
# ---------------------------------------------------------------------------


def test_advanced_django_object_type_init_with_meta_branch():
    """Test object_type.py lines 27: branch where _meta is provided."""

    class Dummy:
        pass

    _meta = DjangoObjectTypeOptions(Dummy)
    # Pass _meta directly to hit the 'if not _meta:' skip
    AdvancedDjangoObjectType.__init_subclass_with_meta__(
        orderset_class=None, _meta=_meta, model=FinalUniqueCoverageModel, fields="__all__"
    )
    assert _meta.orderset_class is None


# ---------------------------------------------------------------------------
# order_arguments_factory.py
# ---------------------------------------------------------------------------


def test_order_arguments_factory_target_orderset_none_skip():
    """A RelatedOrder whose target orderset is ``None`` is skipped from the root type.

    Replaces the previous call to the removed ``create_order_input_type`` helper;
    now asserts against the cached type in ``OrderArgumentsFactory.input_object_types``
    keyed by ``OrderSet.type_name_for()``.  See ``docs/spec-base_type_naming.md``.
    """

    class NoTargetOS(AdvancedOrderSet):
        rel = RelatedOrder(None, field_name="rel")

        class Meta:
            model = FinalUniqueCoverageModel
            fields = ["name"]

    # Clear any cached type from prior runs to keep this test hermetic.
    OrderArgumentsFactory.input_object_types.pop(NoTargetOS.type_name_for(), None)
    OrderArgumentsFactory._type_orderset_registry.pop(NoTargetOS.type_name_for(), None)

    factory = OrderArgumentsFactory(NoTargetOS)
    factory.arguments  # triggers BFS build

    input_type = OrderArgumentsFactory.input_object_types[NoTargetOS.type_name_for()]
    # 'rel' is missing because its target orderset is None — the flat 'name'
    # field still materialises.
    assert "rel" not in input_type._meta.fields
    assert "name" in input_type._meta.fields


# ---------------------------------------------------------------------------
# orderset.py
# ---------------------------------------------------------------------------


def test_orderset_check_permissions_target_class_none_skip():
    """Test orderset.py line 74 skip: target_class is None."""

    class MissingTargetOS(AdvancedOrderSet):
        rel = RelatedOrder(None, field_name="rel")

    os = MissingTargetOS(data=[])
    # path starts with prefix 'rel__' but rel.orderset is None
    os.check_permissions(None, ["rel__title"])


def test_orderset_get_flat_orders_target_orderset_none_skip():
    """Test orderset.py line 96 skip: target_orderset is None."""

    class MissingTargetOS2(AdvancedOrderSet):
        rel = RelatedOrder(None, field_name="rel")

    # Mapping value but target_orderset is None
    data = [{"rel": {"title": "asc"}}]
    flat_orders, distinct_fields = MissingTargetOS2.get_flat_orders(data)
    assert flat_orders == []
    assert distinct_fields == []


# ---------------------------------------------------------------------------
# filterset.py
# ---------------------------------------------------------------------------


def test_filterset_check_permissions_target_class_none_skip():
    """Test filterset.py line 382 skip: target_class is None."""

    class FSMissingRel(AdvancedFilterSet):
        rel = RelatedFilter(None, field_name="rel")

        class Meta:
            model = FinalUniqueCoverageModel
            fields = ["name"]

    fs = FSMissingRel(queryset=FinalUniqueCoverageModel.objects.none())
    fs.check_permissions(None, {"rel__title"})


def test_filterset_collect_filter_fields_non_list_branch():
    """Test filterset.py line 393 skip: 'and' value is not a list."""

    class FSCollect(AdvancedFilterSet):
        class Meta:
            model = FinalUniqueCoverageModel
            fields = ["name"]

    fs = FSCollect(queryset=FinalUniqueCoverageModel.objects.none())
    fields = set()
    data = {"and": "not_a_list"}
    fs._collect_filter_fields(data, fields)
    assert len(fields) == 0


def test_filterset_collect_filter_fields_related_target_none_skip():
    """Test filterset.py line 410 skip: target_class is None."""

    class FSRelMissing(AdvancedFilterSet):
        rel = RelatedFilter(None, field_name="rel")

        class Meta:
            model = FinalUniqueCoverageModel
            fields = []

    fs = FSRelMissing(queryset=FinalUniqueCoverageModel.objects.none())
    fields = set()
    # key starts with rel__ but rel.filterset is None
    fs._collect_filter_fields({"rel__name": "val"}, fields)
    assert len(fields) == 0


def test_filterset_collect_filter_fields_related_child_f_none_skip():
    """Test filterset.py line 412 skip: child_f is None."""

    class ChildFS(AdvancedFilterSet):
        class Meta:
            model = FinalUniqueCoverageModel
            fields = ["name"]

    class FSRel(AdvancedFilterSet):
        rel = RelatedFilter(ChildFS, field_name="rel")

        class Meta:
            model = FinalUniqueCoverageModel
            fields = []

    fs = FSRel(queryset=FinalUniqueCoverageModel.objects.none())
    fields = set()
    # rel__missing is not in ChildFS
    fs._collect_filter_fields({"rel__missing": "val"}, fields)
    assert len(fields) == 0


# ---------------------------------------------------------------------------
# Branch coverage: filters.py line 187->189
# ---------------------------------------------------------------------------


def test_related_filter_get_queryset_assert_when_no_model():
    """Test filters.py line 187->189: assert fires when auto-derive fails (no model)."""

    class EmptyFS(AdvancedFilterSet):
        class Meta:
            model = None
            fields = []

    rf = RelatedFilter(EmptyFS, field_name="rel")
    rf.model = FinalUniqueCoverageModel  # needed so Filter internals don't break

    # Parent must be set for the assertion message
    parent_mock = MagicMock()
    parent_mock.__class__.__name__ = "TestParent"
    rf.parent = parent_mock

    with pytest.raises(AssertionError, match="Expected .get_queryset"):
        rf.get_queryset(MagicMock())


# ---------------------------------------------------------------------------
# Branch coverage: filterset.py line 568->565
# ---------------------------------------------------------------------------


def test_apply_related_queryset_constraints_no_explicit_qs():
    """Test filterset.py line 568->565: loop completes with no explicit querysets."""

    class FSNoExplicit(AdvancedFilterSet):
        # RelatedFilter WITHOUT explicit queryset — _has_explicit_queryset is False
        rel = RelatedFilter("tests.test_final_coverage.FSNoExplicit", field_name="name")

        class Meta:
            model = FinalUniqueCoverageModel
            fields = ["name"]

    fs = FSNoExplicit(queryset=FinalUniqueCoverageModel.objects.none())
    qs = FinalUniqueCoverageModel.objects.none()
    result = fs._apply_related_queryset_constraints(qs)
    # Should return the queryset unchanged
    assert result.query.where == qs.query.where


def test_apply_related_queryset_constraints_explicit_but_none():
    """Test filterset.py line 568->565: _has_explicit_queryset=True but queryset is None."""

    class FSExplicitNone(AdvancedFilterSet):
        rel = RelatedFilter("tests.test_final_coverage.FSExplicitNone", field_name="name")

        class Meta:
            model = FinalUniqueCoverageModel
            fields = ["name"]

    # Manually set the flag to True but leave queryset as None
    FSExplicitNone.related_filters["rel"]._has_explicit_queryset = True
    FSExplicitNone.related_filters["rel"].queryset = None

    fs = FSExplicitNone(queryset=FinalUniqueCoverageModel.objects.none())
    qs = FinalUniqueCoverageModel.objects.none()
    result = fs._apply_related_queryset_constraints(qs)
    # constraint_qs is None so no filter applied — queryset unchanged
    assert result.query.where == qs.query.where


# ---------------------------------------------------------------------------
# Branch coverage: orderset.py line 123->133
# ---------------------------------------------------------------------------


def test_orderset_get_fields_all_no_model():
    """Test orderset.py line 123->133: __all__ with no Meta.model."""

    class OSNoModel(AdvancedOrderSet):
        class Meta:
            model = None
            fields = "__all__"

    fields = OSNoModel.get_fields()
    assert len(fields) == 0


# ---------------------------------------------------------------------------
# object_type.py — converter override fallback branches
# ---------------------------------------------------------------------------


def test_converter_type_not_registered():
    """object_type.py line 249: early return when _type is None."""
    from django_graphene_filters.object_type import _convert_field_to_list_or_connection

    field = MagicMock(spec=models.ManyToOneRel)
    field.related_model = FinalUniqueCoverageModel

    registry = MagicMock()
    registry.get_type_for_model.return_value = None

    dynamic = _convert_field_to_list_or_connection(field, registry)
    assert dynamic.get_type() is None


def test_converter_m2m_field_description_branch():
    """object_type.py line 252: ManyToManyField takes description from field.help_text."""
    from django_graphene_filters.object_type import _convert_field_to_list_or_connection

    field = MagicMock(spec=models.ManyToManyField)
    field.related_model = FinalUniqueCoverageModel
    field.help_text = "M2M help"

    _type = MagicMock()
    _type._meta.connection = True
    _type._meta.filter_fields = None
    _type._meta.filterset_class = None

    registry = MagicMock()
    registry.get_type_for_model.return_value = _type

    dynamic = _convert_field_to_list_or_connection(field, registry)
    with patch("django_graphene_filters.object_type.DjangoConnectionField") as mock_cls:
        mock_cls.return_value = sentinel = MagicMock()
        result = dynamic.get_type()
        assert result is sentinel
        mock_cls.assert_called_once_with(_type, required=True, description="M2M help")


def _make_reverse_rel_field():
    """Create a mock that behaves like a ManyToOneRel for the converter."""
    field = MagicMock()
    field.related_model = FinalUniqueCoverageModel
    # ManyToOneRel gets description via field.field.help_text
    field.field.help_text = ""
    return field


def test_converter_non_advanced_type_falls_back_to_django_filter_connection():
    """object_type.py lines 266-268: non-AdvancedDjangoObjectType with filter_fields."""
    from django_graphene_filters.object_type import _convert_field_to_list_or_connection

    field = _make_reverse_rel_field()

    # MagicMock is not a type, so isinstance(_type, type) is False — hits the fallback.
    _type = MagicMock()
    _type._meta.connection = True
    _type._meta.filter_fields = {"name": ["exact"]}
    _type._meta.filterset_class = None

    registry = MagicMock()
    registry.get_type_for_model.return_value = _type

    dynamic = _convert_field_to_list_or_connection(field, registry)
    with patch("graphene_django.filter.fields.DjangoFilterConnectionField") as mock_cls:
        mock_cls.return_value = sentinel = MagicMock()
        result = dynamic.get_type()
        assert result is sentinel
        mock_cls.assert_called_once_with(_type, required=True, description=None)


def test_converter_connection_without_filter_fields():
    """object_type.py line 270: connection type without filter_fields → DjangoConnectionField."""
    from django_graphene_filters.object_type import _convert_field_to_list_or_connection

    field = _make_reverse_rel_field()

    _type = MagicMock()
    _type._meta.connection = True
    _type._meta.filter_fields = None
    _type._meta.filterset_class = None

    registry = MagicMock()
    registry.get_type_for_model.return_value = _type

    dynamic = _convert_field_to_list_or_connection(field, registry)
    with patch("django_graphene_filters.object_type.DjangoConnectionField") as mock_cls:
        mock_cls.return_value = sentinel = MagicMock()
        result = dynamic.get_type()
        assert result is sentinel
        mock_cls.assert_called_once_with(_type, required=True, description=None)


def test_converter_non_connection_type():
    """object_type.py line 272: non-connection type → DjangoListField."""
    from django_graphene_filters.object_type import _convert_field_to_list_or_connection

    field = _make_reverse_rel_field()

    _type = MagicMock()
    _type._meta.connection = None

    registry = MagicMock()
    registry.get_type_for_model.return_value = _type

    dynamic = _convert_field_to_list_or_connection(field, registry)
    with patch("django_graphene_filters.object_type.DjangoListField") as mock_cls:
        mock_cls.return_value = sentinel = MagicMock()
        result = dynamic.get_type()
        assert result is sentinel
        mock_cls.assert_called_once_with(_type, required=True, description=None)


# ``test_resolve_aggregates_lazy_computation`` lives in ``test_aggregate_coverage.py``
# alongside ``test_resolve_aggregates_no_iterable`` and the root-level stash tests —
# see ``test_resolve_aggregates_lazy_computation_on_nested_connection`` there.
