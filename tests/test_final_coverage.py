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


def test_order_input_type_prefix_no_orderset_branch():
    """Test connection_field.py line 97: branch where provided_orderset_class is falsy."""

    class NodeNoOrder(DjangoObjectType):
        class Meta:
            model = FinalUniqueCoverageModel
            fields = "__all__"
            interfaces = (graphene.relay.Node,)

    field = AdvancedDjangoFilterConnectionField(NodeNoOrder)
    # Patch to ensure provided_orderset_class returns None (though it should by default)
    with patch.object(AdvancedDjangoFilterConnectionField, "provided_orderset_class", None):
        prefix = field.order_input_type_prefix
        assert prefix == "NodeNoOrder"


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

    # Filterset mock
    filterset = MagicMock()
    filterset.form.is_valid.return_value = True
    filterset.qs.distinct.return_value = qs

    with patch("django_graphene_filters.connection_field.get_filterset_class") as mock_get_fs:
        mock_fs_class = MagicMock(return_value=filterset)
        mock_get_fs.return_value = mock_fs_class

        # Triggering resolve_queryset
        # Need orderset_class and order_arg to be truthy to hit 287-288
        args = {"orderBy": [{"name": "asc"}]}
        field.resolve_queryset(connection, [], info, args, {}, mock_fs_class)

        # Verification of logic flow
        assert filterset.qs.distinct.called


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
        orderset_class=None, _meta=_meta, model=FinalUniqueCoverageModel
    )
    assert _meta.orderset_class is None


# ---------------------------------------------------------------------------
# order_arguments_factory.py
# ---------------------------------------------------------------------------


def test_order_arguments_factory_target_orderset_none_skip():
    """Test order_arguments_factory.py line 57 skip: target_orderset is None."""

    class NoTargetOS(AdvancedOrderSet):
        rel = RelatedOrder(None, field_name="rel")

        class Meta:
            model = FinalUniqueCoverageModel
            fields = ["name"]

    factory = OrderArgumentsFactory(NoTargetOS, "NoTarget")
    input_type = factory.create_order_input_type()
    # 'rel' should be missing from fields because its orderset was None
    assert "rel" not in input_type._meta.fields


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
    res = MissingTargetOS2.get_flat_orders(data)
    assert res == []


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
