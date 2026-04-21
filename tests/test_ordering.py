"""Tests for the ordering system: orderset, orders, order_arguments_factory, and object_type."""

import enum
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import graphene
import pytest
from django.db import models

from django_graphene_filters.connection_field import AdvancedDjangoFilterConnectionField
from django_graphene_filters.filterset import AdvancedFilterSet
from django_graphene_filters.object_type import AdvancedDjangoObjectType
from django_graphene_filters.order_arguments_factory import OrderArgumentsFactory, OrderDirection
from django_graphene_filters.orders import BaseRelatedOrder, RelatedOrder
from django_graphene_filters.orderset import AdvancedOrderSet

# ---------------------------------------------------------------------------
# Shared test models / classes
# ---------------------------------------------------------------------------


class OrderModel(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(default="")

    class Meta:
        app_label = "recipes"


class RelatedModel(models.Model):
    title = models.CharField(max_length=100)
    order_model = models.ForeignKey(OrderModel, on_delete=models.CASCADE, null=True)

    class Meta:
        app_label = "recipes"


class ChildOrderSet(AdvancedOrderSet):
    class Meta:
        model = RelatedModel
        fields = ["title"]


class ParentOrderSet(AdvancedOrderSet):
    related = RelatedOrder(ChildOrderSet, field_name="order_model")

    class Meta:
        model = OrderModel
        fields = ["name", "description"]


# ---------------------------------------------------------------------------
# AdvancedOrderSet - get_flat_orders
# ---------------------------------------------------------------------------


class TestGetFlatOrders:
    """Tests for AdvancedOrderSet.get_flat_orders."""

    def test_asc_with_enum(self):
        data = [{"name": OrderDirection.ASC}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["name"]
        assert distinct == []

    def test_desc_with_enum(self):
        data = [{"name": OrderDirection.DESC}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["-name"]
        assert distinct == []

    def test_asc_with_string(self):
        """Plain string values should still work for backward compatibility."""
        data = [{"name": "asc"}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["name"]
        assert distinct == []

    def test_desc_with_string(self):
        data = [{"name": "desc"}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["-name"]
        assert distinct == []

    def test_multiple_fields(self):
        data = [{"name": OrderDirection.ASC}, {"description": OrderDirection.DESC}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["name", "-description"]
        assert distinct == []

    def test_related_order_traversal(self):
        data = [{"related": {"title": OrderDirection.DESC}}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["-order_model__title"]
        assert distinct == []

    def test_related_order_asc(self):
        data = [{"related": {"title": OrderDirection.ASC}}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["order_model__title"]
        assert distinct == []

    def test_with_prefix(self):
        data = [{"name": OrderDirection.DESC}]
        flat, distinct = ParentOrderSet.get_flat_orders(data, prefix="parent__")
        assert flat == ["-parent__name"]
        assert distinct == []

    def test_empty_data(self):
        flat, distinct = ParentOrderSet.get_flat_orders([])
        assert flat == []
        assert distinct == []

    def test_non_mapping_items_skipped(self):
        """Non-mapping items in the list are silently skipped."""
        data = ["not_a_dict", {"name": OrderDirection.ASC}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["name"]
        assert distinct == []

    def test_native_field_mapping_recurse(self):
        """A mapping value for a non-related key should recurse."""
        data = [{"unknown_nested": {"leaf": "desc"}}]
        flat, distinct = AdvancedOrderSet.get_flat_orders(data)
        assert flat == ["-unknown_nested__leaf"]
        assert distinct == []

    def test_asc_distinct_with_enum(self):
        data = [{"name": OrderDirection.ASC_DISTINCT}, {"description": OrderDirection.ASC}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["name", "description"]
        assert distinct == ["name"]

    def test_desc_distinct_with_enum(self):
        data = [{"name": OrderDirection.DESC_DISTINCT}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["-name"]
        assert distinct == ["name"]

    def test_multiple_distinct_fields(self):
        data = [
            {"name": OrderDirection.ASC_DISTINCT},
            {"description": OrderDirection.DESC_DISTINCT},
            {"is_private": OrderDirection.ASC},
        ]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["name", "-description", "is_private"]
        assert distinct == ["name", "description"]

    def test_distinct_on_related_order(self):
        data = [{"related": {"title": OrderDirection.ASC_DISTINCT}}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["order_model__title"]
        assert distinct == ["order_model__title"]

    def test_distinct_with_string_value(self):
        """String values with _distinct suffix should work."""
        data = [{"name": "asc_distinct"}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["name"]
        assert distinct == ["name"]

    def test_contradictory_direction_same_field(self):
        """DESC_DISTINCT + ASC on the same field: flat_orders has both, distinct has one."""
        data = [{"name": OrderDirection.DESC_DISTINCT}, {"name": OrderDirection.ASC}]
        flat, distinct = ParentOrderSet.get_flat_orders(data)
        assert flat == ["-name", "name"]
        assert distinct == ["name"]


# ---------------------------------------------------------------------------
# AdvancedOrderSet - _apply_distinct_postgres deduplication
# ---------------------------------------------------------------------------


class TestApplyDistinctPostgresDedup:
    """Verify _apply_distinct_postgres deduplicates ORDER BY correctly."""

    def test_contradictory_direction_deduplicates(self):
        """Same field with different directions: only the first (distinct) entry kept."""
        from unittest.mock import MagicMock

        qs = MagicMock()
        qs.order_by.return_value = qs
        qs.distinct.return_value = qs

        # Simulates [{name: DESC_DISTINCT}, {name: ASC}]
        result = AdvancedOrderSet._apply_distinct_postgres(
            qs,
            distinct_fields=["name"],
            order_fields=["-name", "name"],
        )

        # ORDER BY should have "-name" once (the distinct entry), NOT "-name, name"
        qs.order_by.assert_called_once_with("-name")
        qs.distinct.assert_called_once_with("name")

    def test_distinct_field_not_in_order_fields(self):
        """A distinct field not present in order_fields gets appended bare."""
        from unittest.mock import MagicMock

        qs = MagicMock()
        qs.order_by.return_value = qs
        qs.distinct.return_value = qs

        result = AdvancedOrderSet._apply_distinct_postgres(
            qs,
            distinct_fields=["category"],
            order_fields=["name"],
        )

        # category leads (distinct), then name (tiebreaker)
        qs.order_by.assert_called_once_with("category", "name")
        qs.distinct.assert_called_once_with("category")

    def test_multiple_distinct_fields_dedup(self):
        """Multiple distinct fields are deduplicated individually."""
        from unittest.mock import MagicMock

        qs = MagicMock()
        qs.order_by.return_value = qs
        qs.distinct.return_value = qs

        result = AdvancedOrderSet._apply_distinct_postgres(
            qs,
            distinct_fields=["name", "status"],
            order_fields=["name", "-status", "created"],
        )

        # distinct fields lead (name, -status), then non-distinct tiebreakers (created)
        qs.order_by.assert_called_once_with("name", "-status", "created")
        qs.distinct.assert_called_once_with("name", "status")


class TestApplyDistinctGroupByFallback:
    """Verify apply_distinct falls back to emulated when queryset has GROUP BY."""

    def test_postgres_with_group_by_falls_back_to_emulated(self):
        """On PostgreSQL, a queryset with GROUP BY skips native DISTINCT ON."""
        from unittest.mock import MagicMock, patch

        qs = MagicMock()
        qs.query.group_by = True  # Simulates an aggregate-annotated queryset
        qs.annotate.return_value = qs
        qs.filter.return_value = qs

        with (
            patch("django_graphene_filters.conf.settings.IS_POSTGRESQL", True),
            patch.object(AdvancedOrderSet, "_apply_distinct_emulated") as mock_emulated,
            patch.object(AdvancedOrderSet, "_apply_distinct_postgres") as mock_native,
        ):
            mock_emulated.return_value = qs

            AdvancedOrderSet.apply_distinct(qs, ["name"], ["name"])

            mock_emulated.assert_called_once()
            mock_native.assert_not_called()

    def test_postgres_without_group_by_uses_native(self):
        """On PostgreSQL, a queryset without GROUP BY uses native DISTINCT ON."""
        from unittest.mock import MagicMock, patch

        qs = MagicMock()
        qs.query.group_by = None

        with (
            patch("django_graphene_filters.conf.settings.IS_POSTGRESQL", True),
            patch.object(AdvancedOrderSet, "_apply_distinct_emulated") as mock_emulated,
            patch.object(AdvancedOrderSet, "_apply_distinct_postgres") as mock_native,
        ):
            mock_native.return_value = qs

            AdvancedOrderSet.apply_distinct(qs, ["name"], ["name"])

            mock_native.assert_called_once()
            mock_emulated.assert_not_called()


class TestRelatedOrderInheritance:
    """Verify RelatedOrder declarations are inherited from base classes."""

    def test_subclass_inherits_related_orders(self):
        """A subclass preserves its base class's RelatedOrder declarations."""

        class BaseOrder(AdvancedOrderSet):
            related = RelatedOrder(ChildOrderSet, field_name="order_model")

            class Meta:
                model = OrderModel
                fields = ["name"]

        class SubOrder(BaseOrder):
            class Meta:
                model = OrderModel
                fields = ["name", "description"]

        # The subclass should still see the inherited `related` RelatedOrder
        assert "related" in SubOrder.related_orders
        assert isinstance(SubOrder.related_orders["related"], RelatedOrder)

    def test_subclass_can_override_related_order(self):
        """A subclass can override an inherited RelatedOrder by redeclaring it."""

        class BaseOrder(AdvancedOrderSet):
            related = RelatedOrder(ChildOrderSet, field_name="order_model")

            class Meta:
                model = OrderModel
                fields = ["name"]

        class SubOrder(BaseOrder):
            # Override with a different field_name
            related = RelatedOrder(ChildOrderSet, field_name="other_model")

            class Meta:
                model = OrderModel
                fields = ["name"]

        assert SubOrder.related_orders["related"].field_name == "other_model"

    def test_get_fields_exposes_inherited_related_orders(self):
        """get_fields() on a subclass includes inherited RelatedOrder entries."""

        class BaseOrder(AdvancedOrderSet):
            related = RelatedOrder(ChildOrderSet, field_name="order_model")

            class Meta:
                model = OrderModel
                fields = ["name"]

        class SubOrder(BaseOrder):
            class Meta:
                model = OrderModel
                fields = ["name"]

        fields = SubOrder.get_fields()
        assert "related" in fields
        assert fields["related"] is not None  # has a RelatedOrder instance


# ---------------------------------------------------------------------------
# AdvancedOrderSet - get_fields
# ---------------------------------------------------------------------------


class TestGetFields:
    def test_list_meta_fields(self):
        fields = ParentOrderSet.get_fields()
        assert "name" in fields
        assert "description" in fields
        assert fields["name"] is None  # flat field, no related order

    def test_related_orders_included(self):
        fields = ParentOrderSet.get_fields()
        assert "related" in fields
        assert isinstance(fields["related"], RelatedOrder)

    def test_dict_meta_fields(self):
        class DictFieldsOrderSet(AdvancedOrderSet):
            class Meta:
                model = OrderModel
                fields = {"name": ["asc", "desc"]}

        fields = DictFieldsOrderSet.get_fields()
        assert "name" in fields
        assert fields["name"] is None

    def test_no_meta(self):
        class BareOrderSet(AdvancedOrderSet):
            pass

        assert BareOrderSet.get_fields() == OrderedDict()


# ---------------------------------------------------------------------------
# AdvancedOrderSet - __init__ and check_permissions
# ---------------------------------------------------------------------------


class TestOrderSetInit:
    def test_applies_ordering_to_queryset(self):
        qs = MagicMock()
        qs.order_by.return_value = qs
        data = [{"name": OrderDirection.ASC}]
        orderset = ParentOrderSet(data=data, queryset=qs)
        qs.order_by.assert_called_once_with("name")
        assert orderset.qs is qs

    def test_no_data_no_ordering(self):
        qs = MagicMock()
        orderset = ParentOrderSet(data=[], queryset=qs)
        qs.order_by.assert_not_called()

    def test_no_queryset_no_ordering(self):
        orderset = ParentOrderSet(data=[{"name": OrderDirection.ASC}], queryset=None)
        assert orderset.qs is None

    def test_check_permissions_called(self):
        qs = MagicMock()
        qs.order_by.return_value = qs

        class PermOrderSet(AdvancedOrderSet):
            perm_called = False

            def check_name_permission(self, request):
                PermOrderSet.perm_called = True

            class Meta:
                model = OrderModel
                fields = ["name"]

        PermOrderSet(data=[{"name": "asc"}], queryset=qs, request="fake_request")
        assert PermOrderSet.perm_called

    def test_check_permissions_strips_dash(self):
        """Permission method lookup should ignore leading '-'."""
        qs = MagicMock()
        qs.order_by.return_value = qs

        class DashPermOrderSet(AdvancedOrderSet):
            checked = False

            def check_name_permission(self, request):
                DashPermOrderSet.checked = True

            class Meta:
                model = OrderModel
                fields = ["name"]

        DashPermOrderSet(data=[{"name": "desc"}], queryset=qs)
        assert DashPermOrderSet.checked

    def test_permission_delegated_to_child_orderset(self):
        """Permission defined on a child orderset should be enforced via related traversal."""
        qs = MagicMock()
        qs.order_by.return_value = qs

        class ChildPerm(AdvancedOrderSet):
            child_checked = False

            def check_title_permission(self, request):
                ChildPerm.child_checked = True

            class Meta:
                model = RelatedModel
                fields = ["title"]

        class ParentPerm(AdvancedOrderSet):
            child_rel = RelatedOrder(ChildPerm, field_name="order_model")

            class Meta:
                model = OrderModel
                fields = ["name"]

        # Ordering through a related path should trigger the child's permission check
        ParentPerm(data=[{"child_rel": {"title": "asc"}}], queryset=qs, request="req")
        assert ChildPerm.child_checked

    def test_permission_raises_through_relation(self):
        """A permission error on a child orderset should propagate up."""
        qs = MagicMock()
        qs.order_by.return_value = qs

        class StrictChild(AdvancedOrderSet):
            def check_title_permission(self, request):
                raise PermissionError("denied")

            class Meta:
                model = RelatedModel
                fields = ["title"]

        class StrictParent(AdvancedOrderSet):
            child_rel = RelatedOrder(StrictChild, field_name="order_model")

            class Meta:
                model = OrderModel
                fields = ["name"]

        with pytest.raises(PermissionError, match="denied"):
            StrictParent(data=[{"child_rel": {"title": "desc"}}], queryset=qs)

    def test_no_false_delegation_for_flat_fields(self):
        """Flat fields on the parent should not trigger child permission checks."""
        qs = MagicMock()
        qs.order_by.return_value = qs

        class NoisyChild(AdvancedOrderSet):
            def check_title_permission(self, request):
                raise PermissionError("should not fire")

            class Meta:
                model = RelatedModel
                fields = ["title"]

        class QuietParent(AdvancedOrderSet):
            child_rel = RelatedOrder(NoisyChild, field_name="order_model")

            class Meta:
                model = OrderModel
                fields = ["name"]

        # Ordering by a flat field on the parent should NOT touch the child
        QuietParent(data=[{"name": "asc"}], queryset=qs)


# ---------------------------------------------------------------------------
# OrderSetMetaclass
# ---------------------------------------------------------------------------


def test_metaclass_attaches_related_orders():
    assert "related" in ParentOrderSet.related_orders
    assert isinstance(ParentOrderSet.related_orders["related"], RelatedOrder)


def test_metaclass_binds_orderset():
    order = ParentOrderSet.related_orders["related"]
    assert order.bound_orderset is ParentOrderSet


# ---------------------------------------------------------------------------
# orders.py - BaseRelatedOrder / RelatedOrder
# ---------------------------------------------------------------------------


class TestBaseRelatedOrder:
    def test_orderset_property_returns_class(self):
        order = BaseRelatedOrder(orderset=ChildOrderSet)
        assert order.orderset is ChildOrderSet

    def test_orderset_setter(self):
        order = BaseRelatedOrder(orderset=ChildOrderSet)
        order.orderset = ParentOrderSet
        assert order.orderset is ParentOrderSet

    def test_lazy_string_resolution(self):
        with patch(
            "django_graphene_filters.orders.LazyRelatedClassMixin.resolve_lazy_class",
            return_value=ChildOrderSet,
        ):
            order = BaseRelatedOrder(orderset="some.path.ChildOrderSet")
            assert order.orderset is ChildOrderSet

    def test_bind_orderset_only_once(self):
        order = BaseRelatedOrder(orderset=ChildOrderSet)
        order.bind_orderset(ParentOrderSet)
        assert order.bound_orderset is ParentOrderSet
        # Second bind should be ignored
        order.bind_orderset(ChildOrderSet)
        assert order.bound_orderset is ParentOrderSet


class TestRelatedOrder:
    def test_field_name_stored(self):
        order = RelatedOrder(orderset=ChildOrderSet, field_name="my_field")
        assert order.field_name == "my_field"

    def test_inherits_orderset_property(self):
        order = RelatedOrder(orderset=ChildOrderSet, field_name="f")
        assert order.orderset is ChildOrderSet


# ---------------------------------------------------------------------------
# OrderDirection enum
# ---------------------------------------------------------------------------


def test_order_direction_values():
    assert OrderDirection.ASC.value == "asc"
    assert OrderDirection.DESC.value == "desc"
    assert isinstance(OrderDirection.ASC, enum.Enum)


# ---------------------------------------------------------------------------
# OrderArgumentsFactory
# ---------------------------------------------------------------------------


class TestOrderArgumentsFactory:
    """Tests for the public ``OrderArgumentsFactory`` API under class-based naming.

    See ``docs/spec-base_type_naming.md``: the legacy ``create_order_input_type``
    recursive helper and ``input_type_prefix`` parameter are gone.  The public
    entry point is ``.arguments``; emitted GraphQL types are cached in
    ``OrderArgumentsFactory.input_object_types`` keyed by
    ``OrderSet.type_name_for()``.
    """

    def test_arguments_contains_order_by(self):
        factory = OrderArgumentsFactory(ParentOrderSet)
        args = factory.arguments
        assert "orderBy" in args
        assert isinstance(args["orderBy"], graphene.Argument)

    def test_flat_orderset_root_type_exposes_declared_fields(self):
        """An OrderSet with only flat Meta.fields produces a root type with those fields.

        Replaces the previous ``test_create_order_input_type_flat_fields`` which
        called the removed ``create_order_input_type`` helper directly.
        """
        OrderArgumentsFactory.input_object_types.pop(ChildOrderSet.type_name_for(), None)
        OrderArgumentsFactory._type_orderset_registry.pop(ChildOrderSet.type_name_for(), None)

        factory = OrderArgumentsFactory(ChildOrderSet)
        factory.arguments  # triggers BFS build

        input_type = OrderArgumentsFactory.input_object_types[ChildOrderSet.type_name_for()]
        assert input_type.__name__ == "ChildOrderSetInputType"
        assert "title" in input_type._meta.fields

    def test_orderset_root_type_exposes_flat_and_related_fields(self):
        """An OrderSet with flat fields and a RelatedOrder exposes both at the root.

        Replaces the previous ``test_create_order_input_type_with_related``.  The
        RelatedOrder field is emitted via a lambda ref to the target OrderSet's
        root type (see ``docs/spec-base_type_naming.md``).
        """
        for cls in (ParentOrderSet, ChildOrderSet):
            OrderArgumentsFactory.input_object_types.pop(cls.type_name_for(), None)
            OrderArgumentsFactory._type_orderset_registry.pop(cls.type_name_for(), None)

        factory = OrderArgumentsFactory(ParentOrderSet)
        factory.arguments

        parent_type = OrderArgumentsFactory.input_object_types[ParentOrderSet.type_name_for()]
        fields = parent_type._meta.fields
        assert "name" in fields
        assert "description" in fields
        assert "related" in fields
        # BFS also built the target OrderSet's root type.
        assert ChildOrderSet.type_name_for() in OrderArgumentsFactory.input_object_types

    def test_root_type_is_reused_across_factory_instances(self):
        """Two factories bound to the same OrderSet share the same cached root type.

        Replaces the previous ``test_input_type_caching``.  This is the class-based
        naming guarantee: the emitted GraphQL type for an OrderSet is stable across
        every connection / factory invocation that reaches it.
        """
        OrderArgumentsFactory.input_object_types.pop(ChildOrderSet.type_name_for(), None)
        OrderArgumentsFactory._type_orderset_registry.pop(ChildOrderSet.type_name_for(), None)

        factory_a = OrderArgumentsFactory(ChildOrderSet)
        factory_a.arguments
        type_a = OrderArgumentsFactory.input_object_types[ChildOrderSet.type_name_for()]

        factory_b = OrderArgumentsFactory(ChildOrderSet)
        factory_b.arguments
        type_b = OrderArgumentsFactory.input_object_types[ChildOrderSet.type_name_for()]

        assert type_a is type_b

    def test_circular_related_order_resolves_via_lambda(self):
        """Circular RelatedOrder references resolve cleanly via BFS + lambda refs.

        Under the old implementation, mutual ``A → B → A`` references relied on a
        ``_building`` guard to break recursion and emitted an empty type for the
        back-edge.  Under class-based naming (``docs/spec-base_type_naming.md``)
        the lambda-ref pattern handles cycles naturally: BFS visits each class
        once, and the back-edge lambda resolves at schema-finalize time.
        """

        class CircularAOrder(AdvancedOrderSet):
            b = RelatedOrder("CircularBOrder", field_name="b_rel")

            class Meta:
                model = OrderModel
                fields = ["name"]

        class CircularBOrder(AdvancedOrderSet):
            a = RelatedOrder(CircularAOrder, field_name="a_rel")

            class Meta:
                model = RelatedModel
                fields = ["title"]

        # Resolve the lazy string reference
        CircularAOrder.related_orders["b"]._orderset = CircularBOrder

        # Clear any cached types for these classes from prior test runs
        for cls in (CircularAOrder, CircularBOrder):
            OrderArgumentsFactory.input_object_types.pop(cls.type_name_for(), None)
            OrderArgumentsFactory._type_orderset_registry.pop(cls.type_name_for(), None)

        factory = OrderArgumentsFactory(CircularAOrder)
        # Must not raise RecursionError — BFS visits each class once.
        factory.arguments

        # Both root types materialise, and each exposes its own fields as well as
        # the back-edge to the other OrderSet.
        a_type = OrderArgumentsFactory.input_object_types[CircularAOrder.type_name_for()]
        b_type = OrderArgumentsFactory.input_object_types[CircularBOrder.type_name_for()]
        assert a_type is not None and b_type is not None
        assert "name" in a_type._meta.fields
        assert "b" in a_type._meta.fields
        assert "title" in b_type._meta.fields
        assert "a" in b_type._meta.fields


# ---------------------------------------------------------------------------
# AdvancedDjangoObjectType
# ---------------------------------------------------------------------------


class OrderFilterSet(AdvancedFilterSet):
    class Meta:
        model = OrderModel
        fields = ["name"]


class TestAdvancedDjangoObjectType:
    def test_orderset_class_stored_on_meta(self):
        class TestNode(AdvancedDjangoObjectType):
            class Meta:
                model = OrderModel
                interfaces = (graphene.Node,)
                fields = "__all__"
                filterset_class = OrderFilterSet
                orderset_class = ParentOrderSet

        assert TestNode._meta.orderset_class is ParentOrderSet

    def test_orderset_class_defaults_to_none(self):
        class NoOrderNode(AdvancedDjangoObjectType):
            class Meta:
                model = RelatedModel
                interfaces = (graphene.Node,)
                fields = "__all__"

        assert NoOrderNode._meta.orderset_class is None

    def test_filterset_class_still_works(self):
        class BothNode(AdvancedDjangoObjectType):
            class Meta:
                model = OrderModel
                interfaces = (graphene.Node,)
                fields = "__all__"
                filterset_class = OrderFilterSet
                orderset_class = ParentOrderSet

        assert BothNode._meta.filterset_class is OrderFilterSet


# ---------------------------------------------------------------------------
# Connection field - ordering integration
# ---------------------------------------------------------------------------


class IntegrationFilterSet(AdvancedFilterSet):
    class Meta:
        model = OrderModel
        fields = ["name"]


class IntegrationNode(AdvancedDjangoObjectType):
    class Meta:
        model = OrderModel
        interfaces = (graphene.Node,)
        fields = "__all__"
        filterset_class = IntegrationFilterSet
        orderset_class = ParentOrderSet


class TestConnectionFieldOrdering:
    def test_ordering_args_populated_from_meta(self):
        field = AdvancedDjangoFilterConnectionField(IntegrationNode)
        assert "orderBy" in field.ordering_args

    def test_ordering_args_in_merged_args(self):
        field = AdvancedDjangoFilterConnectionField(IntegrationNode)
        assert "orderBy" in field.args

    def test_no_ordering_without_orderset(self):
        class PlainNode(AdvancedDjangoObjectType):
            class Meta:
                model = RelatedModel
                interfaces = (graphene.Node,)
                fields = "__all__"
                filter_fields = ["title"]

        field = AdvancedDjangoFilterConnectionField(PlainNode)
        assert field.ordering_args == {}
        assert "orderBy" not in field.args

    def test_orderset_class_from_init_arg(self):
        """orderset_class passed directly to the field should also work."""

        class DirectNode(AdvancedDjangoObjectType):
            class Meta:
                model = RelatedModel
                interfaces = (graphene.Node,)
                fields = "__all__"

        field = AdvancedDjangoFilterConnectionField(
            DirectNode,
            orderset_class=ChildOrderSet,
        )
        assert field.provided_orderset_class is ChildOrderSet
        assert "orderBy" in field.ordering_args

    def test_order_input_type_name_is_class_based(self):
        """The order input type name derives from the OrderSet class, not the node.

        Replaces the previous ``test_default_order_input_type_prefix`` which asserted
        on the removed ``order_input_type_prefix`` property.  The spec mandates that
        two connection fields reaching the same OrderSet share the same GraphQL type.
        """
        field = AdvancedDjangoFilterConnectionField(IntegrationNode)
        order_arg_type = field.ordering_args["orderBy"].type.of_type.of_type
        # Class-based naming: ``{ParentOrderSet.__name__}InputType`` — no node prefix.
        assert order_arg_type.__name__ == ParentOrderSet.type_name_for()
        assert "IntegrationNode" not in order_arg_type.__name__

        # Reuse across fields: two connections bound to the same OrderSet share the
        # same emitted GraphQL type object.
        field_b = AdvancedDjangoFilterConnectionField(IntegrationNode)
        assert (
            field.ordering_args["orderBy"].type.of_type.of_type
            is field_b.ordering_args["orderBy"].type.of_type.of_type
        )
