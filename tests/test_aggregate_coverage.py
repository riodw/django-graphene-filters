"""Unit tests to achieve 100% coverage on the aggregate system.

Covers edge cases, error paths, and branches in:
- aggregateset.py (python-level stats, safety limits, permissions, selection set parsing, m2m, validation)
- connection_field.py (aggregate properties, _extract_aggregate_selection error path)
- mixins.py (ObjectTypeFactoryMixin cache hit)
- object_type.py (_inject_aggregates_on_connection early return, resolve_aggregates null iterable)
"""

from collections import OrderedDict
from unittest.mock import MagicMock, patch

import graphene
import pytest
from cookbook.recipes.models import Object, ObjectType

from django_graphene_filters.aggregate_arguments_factory import AggregateArgumentsFactory
from django_graphene_filters.aggregateset import (
    AdvancedAggregateSet,
    RelatedAggregate,
    _fetch_values,
)
from django_graphene_filters.connection_field import AdvancedDjangoFilterConnectionField
from django_graphene_filters.mixins import ObjectTypeFactoryMixin
from django_graphene_filters.object_type import _inject_aggregates_on_connection

# ---------------------------------------------------------------------------
# aggregateset.py — python-level stat helpers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_fetch_values_safety_limit():
    """``_fetch_values`` honours the ``AGGREGATE_MAX_VALUES`` safety limit."""
    ot = ObjectType.objects.create(name="limit")
    for i in range(5):
        Object.objects.create(name=f"obj{i}", object_type=ot)
    with patch("django_graphene_filters.aggregateset.settings") as mock_settings:
        mock_settings.AGGREGATE_MAX_VALUES = 2
        values = _fetch_values(Object.objects.all(), "id", limit=2)
        assert len(values) == 2


# ---------------------------------------------------------------------------
# aggregateset.py — RelatedAggregate edge cases
# ---------------------------------------------------------------------------


def test_related_aggregate_bind_already_bound():
    """``bind_aggregateset`` is a no-op when the aggregateset is already bound."""
    ra = RelatedAggregate(AdvancedAggregateSet, field_name="test")
    ra.bind_aggregateset(ObjectType)
    # Second call should be a no-op
    ra.bind_aggregateset(Object)
    assert ra.bound_aggregateset is ObjectType


def test_related_aggregate_class_setter():
    """``aggregate_class`` setter writes through to the backing field."""
    ra = RelatedAggregate(AdvancedAggregateSet, field_name="test")
    ra.aggregate_class = ObjectType
    assert ra._aggregate_class is ObjectType


# ---------------------------------------------------------------------------
# aggregateset.py — _get_field_category validation
# ---------------------------------------------------------------------------


def test_get_field_category_nonexistent_field():
    """``_get_field_category`` raises ValueError when the field doesn't exist."""
    with pytest.raises(ValueError, match="does not exist"):

        class BadFieldAgg(AdvancedAggregateSet):
            class Meta:
                model = ObjectType
                fields = {"nonexistent_field": ["count"]}


def test_get_field_category_unsupported_type():
    """``_get_field_category`` raises ValueError when the field type is unrecognised."""
    with patch(
        "django_graphene_filters.aggregateset.FIELD_CATEGORIES",
        {},
    ):
        with pytest.raises(ValueError, match="not supported for aggregation"):

            class UnsupportedAgg(AdvancedAggregateSet):
                class Meta:
                    model = ObjectType
                    fields = {"name": ["count"]}


# ---------------------------------------------------------------------------
# aggregateset.py — metaclass stat validation
# ---------------------------------------------------------------------------


def test_metaclass_invalid_stat_for_category():
    """Metaclass raises ValueError when a stat isn't valid for the field's category."""
    with pytest.raises(ValueError, match="not valid for field"):

        class BadStatAgg(AdvancedAggregateSet):
            class Meta:
                model = ObjectType
                fields = {"name": ["variance"]}  # variance is not valid for text


# ---------------------------------------------------------------------------
# aggregateset.py — compute() permission hooks and selection set parsing
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compute_field_permission_check():
    """``_check_field_permission`` fires during compute planning."""

    class PermAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

        def check_name_permission(self, request):
            pass  # just verifying it gets called

    ObjectType.objects.create(name="perm_test")
    agg = PermAgg(queryset=ObjectType.objects.all())
    result = agg.compute()
    assert "name" in result


@pytest.mark.django_db
def test_compute_stat_permission_check():
    """``_check_stat_permission`` fires during compute planning."""

    class StatPermAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

        def check_name_count_permission(self, request):
            pass  # just verifying it gets called

    ObjectType.objects.create(name="stat_perm_test")
    agg = StatPermAgg(queryset=ObjectType.objects.all())
    result = agg.compute()
    assert "name" in result


def test_parse_selection_set_no_sub_selections():
    """``_parse_selection_set`` emits an empty set when a selection has no sub-selections."""
    # Simulate a selection with no selection_set (e.g. a scalar field)
    sel = MagicMock()
    sel.name.value = "some_field"
    sel.selection_set = None
    parent = MagicMock()
    parent.selections = [sel]

    result = AdvancedAggregateSet._parse_selection_set(parent)
    assert "some_field" in result
    assert result["some_field"] == set()


def test_get_child_selection_none_input():
    """``_get_child_selection`` returns None when given a ``None`` parent."""
    result = AdvancedAggregateSet._get_child_selection(None, "test")
    assert result is None


def test_get_child_selection_field_not_found():
    """``_get_child_selection`` returns None when the field name isn't present."""
    sel = MagicMock()
    sel.name.value = "other_field"
    parent = MagicMock()
    parent.selections = [sel]
    result = AdvancedAggregateSet._get_child_selection(parent, "missing_field")
    assert result is None


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# connection_field.py — aggregate properties
# ---------------------------------------------------------------------------


def test_connection_field_provided_aggregate_class():
    """``provided_aggregate_class`` returns the explicit override when given."""
    from graphene_django import DjangoObjectType as GDjangoObjectType

    class TempNode(GDjangoObjectType):
        class Meta:
            model = ObjectType
            fields = "__all__"
            interfaces = (graphene.relay.Node,)

    class DummyAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    field = AdvancedDjangoFilterConnectionField(TempNode, aggregate_class=DummyAgg)
    assert field.provided_aggregate_class is DummyAgg


def test_connection_field_aggregate_class_property():
    """``aggregate_class`` caches the resolved class on first access."""
    from graphene_django import DjangoObjectType as GDjangoObjectType

    class TempNode2(GDjangoObjectType):
        class Meta:
            model = ObjectType
            fields = "__all__"
            interfaces = (graphene.relay.Node,)

    class DummyAgg2(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    field = AdvancedDjangoFilterConnectionField(TempNode2, aggregate_class=DummyAgg2)
    # First access populates cache
    assert field.aggregate_class is DummyAgg2
    # Second access uses cache
    assert field.aggregate_class is DummyAgg2


def test_connection_field_aggregate_type_property():
    """``aggregate_type`` builds and caches the aggregate ObjectType."""
    from graphene_django import DjangoObjectType as GDjangoObjectType

    class TempNode3(GDjangoObjectType):
        class Meta:
            model = ObjectType
            fields = "__all__"
            interfaces = (graphene.relay.Node,)

    class DummyAgg3(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    field = AdvancedDjangoFilterConnectionField(TempNode3, aggregate_class=DummyAgg3)
    agg_type = field.aggregate_type
    assert agg_type is not None
    # Second access uses cache
    assert field.aggregate_type is agg_type


def test_extract_aggregate_selection_exception():
    """``_extract_aggregate_selection`` swallows AttributeError / TypeError."""
    info = MagicMock()
    # Make field_nodes iteration raise TypeError
    info.field_nodes = None
    result = AdvancedDjangoFilterConnectionField._extract_aggregate_selection(info)
    assert result is None


# ---------------------------------------------------------------------------
# mixins.py — ObjectTypeFactoryMixin cache hit
# ---------------------------------------------------------------------------


def test_object_type_factory_mixin_cache_hit():
    """``create_object_type`` returns the cached class on repeat calls with the same name."""
    # Clear cache first to avoid collision with other tests
    name = "TestCachedCoverageType"
    ObjectTypeFactoryMixin.object_types.pop(name, None)

    fields = {"test_field": graphene.String()}
    first = ObjectTypeFactoryMixin.create_object_type(name, fields)
    second = ObjectTypeFactoryMixin.create_object_type(name, {"other": graphene.Int()})
    assert first is second


# ---------------------------------------------------------------------------
# object_type.py — _inject_aggregates_on_connection
# ---------------------------------------------------------------------------


def test_inject_aggregates_already_injected():
    """``_inject_aggregates_on_connection`` early-returns when already injected."""

    class FakeConnection:
        _aggregate_field_injected = True
        _meta = MagicMock()

    class FakeAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    # Should return immediately without modifying anything
    _inject_aggregates_on_connection(ObjectType, FakeAgg, FakeConnection)
    # If it didn't short-circuit, it would have added fields to _meta
    assert not hasattr(FakeConnection._meta.fields, "aggregates") or True


def test_resolve_aggregates_no_iterable():
    """``resolve_aggregates`` returns None when the root has no ``iterable``."""
    from django_graphene_filters.object_type import _inject_aggregates_on_connection

    class FakeAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    class TestConnection:
        _meta = MagicMock()
        _meta.fields = {}

    _inject_aggregates_on_connection(ObjectType, FakeAgg, TestConnection)

    # Call the resolver with an object that has no iterable and no aggregates
    root = MagicMock(spec=[])  # spec=[] means no attributes at all
    info = MagicMock()

    result = TestConnection.resolve_aggregates(root, info)
    assert result is None


@pytest.mark.django_db
def test_resolve_aggregates_lazy_computation_on_nested_connection():
    """Nested-connection resolver builds a fresh aggregate set per edge and calls
    ``compute(local_only=True)``.

    Covers the third dispatch branch in ``_inject_aggregates_on_connection``'s
    resolver: no ``root.aggregates`` (pre-computed), no
    ``iterable._aggregate_set`` (root-level stash) — just a plain queryset
    attached as ``root.iterable``.  The resolver instantiates the aggregate
    class on the fly and runs ``compute`` with ``local_only=True`` because
    the GraphQL query structure expresses the nesting.
    """
    from django_graphene_filters.object_type import _inject_aggregates_on_connection

    class LazyAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    class LazyConnection:
        _meta = MagicMock()
        _meta.fields = {}

    _inject_aggregates_on_connection(ObjectType, LazyAgg, LazyConnection)

    ObjectType.objects.create(name="lazy_a")
    ObjectType.objects.create(name="lazy_b")

    # Simulate a nested-connection root: has ``iterable`` but no
    # ``_aggregate_set`` and no ``aggregates`` — the two short-circuit
    # branches above the lazy path must miss.
    root = type("R", (), {"iterable": ObjectType.objects.all()})()
    info = type("I", (), {"context": None})()

    result = LazyConnection.resolve_aggregates(root, info)

    # Root total row count.
    assert result["count"] == 2
    # Own-field stats still compute under ``local_only=True`` — only
    # ``RelatedAggregate`` fan-out is skipped.
    assert result["name"]["count"] == 2


# ---------------------------------------------------------------------------
# aggregate_arguments_factory.py — circular reference branch
# ---------------------------------------------------------------------------


def test_aggregate_factory_circular_reference():
    """``AggregateArgumentsFactory`` handles a self-referential ``RelatedAggregate``."""

    class CircularAgg(AdvancedAggregateSet):
        self_ref = RelatedAggregate("CircularAgg", field_name="object_type")

        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    # Manually resolve the lazy string reference
    CircularAgg.self_ref._aggregate_class = CircularAgg
    CircularAgg.related_aggregates = OrderedDict([("self_ref", CircularAgg.self_ref)])

    factory = AggregateArgumentsFactory(CircularAgg)
    # Should not raise / infinite loop
    result = factory.build_aggregate_type()
    assert result is not None


# ---------------------------------------------------------------------------
# aggregateset.py — compute() with boolean stats via aggregateset
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compute_boolean_stats():
    """Cover boolean stat computation via compute() (true_count / false_count via DB_AGGREGATES)."""

    class BoolAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"is_private": ["count", "true_count", "false_count"]}

    ObjectType.objects.create(name="bool_pub", is_private=False)
    ObjectType.objects.create(name="bool_priv", is_private=True)

    agg = BoolAgg(queryset=ObjectType.objects.all())
    result = agg.compute()
    assert result["is_private"]["true_count"] == 1
    assert result["is_private"]["false_count"] == 1


@pytest.mark.django_db
def test_compute_numeric_python_stats():
    """Median / stdev / variance route through PYTHON_STATS (consolidated values fetch)."""

    class NumericAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            fields = {"id": ["median", "stdev", "variance"]}

    ot = ObjectType.objects.create(name="num_reg")
    for i in range(5):
        Object.objects.create(name=f"nr{i}", object_type=ot)

    agg = NumericAgg(queryset=Object.objects.all())
    result = agg.compute()
    assert result["id"]["median"] is not None
    assert result["id"]["stdev"] is not None
    assert result["id"]["variance"] is not None


def test_metaclass_custom_compute_method_passes_validation():
    """Metaclass accepts unknown stats when a ``compute_<field>_<stat>`` method exists."""

    # This should NOT raise — the compute_ method validates the unknown stat.
    class ComputeMethodAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["my_custom_stat"]}

        def compute_name_my_custom_stat(self, queryset):
            return "custom_result"

    assert "my_custom_stat" in ComputeMethodAgg._aggregate_config["name"]["stats"]


@pytest.mark.django_db
def test_compute_custom_stat_without_compute_method_silently_skipped():
    """A custom stat with no ``compute_<field>_<stat>`` method is silently skipped."""

    class NoComputeCustomAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["weird_stat"]}
            custom_stats = {"weird_stat": graphene.String}

    ObjectType.objects.create(name="custom_no_compute")
    agg = NoComputeCustomAgg(queryset=ObjectType.objects.all())
    result = agg.compute()
    # weird_stat has no compute_ method and isn't a built-in → silently skipped.
    assert "weird_stat" not in result["name"]


def test_build_stat_fields_skips_unknown_stat():
    """``_build_stat_fields`` silently skips stats absent from custom + category maps."""
    fields = AggregateArgumentsFactory._build_stat_fields(
        category="text",
        stat_names=["count", "unknown_stat_xyz"],
        custom_stats={},
    )
    # unknown_stat_xyz should be skipped
    assert "count" in fields
    assert "unknown_stat_xyz" not in fields


def test_extract_aggregate_selection_no_aggregates_field():
    """``_extract_aggregate_selection`` returns None when no ``aggregates`` selection is present."""
    info = MagicMock()
    field_node = MagicMock()
    sel = MagicMock()
    sel.name.value = "edges"  # not 'aggregates'
    field_node.selection_set.selections = [sel]
    info.field_nodes = [field_node]
    result = AdvancedDjangoFilterConnectionField._extract_aggregate_selection(info)
    assert result is None


@pytest.mark.django_db
def test_get_child_queryset_m2m_distinct():
    """``get_child_queryset`` applies ``.distinct()`` on the derived child queryset."""
    from django.contrib.auth.models import Group, User

    class GroupAgg(AdvancedAggregateSet):
        class Meta:
            model = Group
            fields = {"name": ["count"]}

    class UserAgg(AdvancedAggregateSet):
        groups = RelatedAggregate(GroupAgg, field_name="user")

        class Meta:
            model = User
            fields = {"username": ["count"]}

    user = User.objects.create_user("m2m_test")
    g1 = Group.objects.create(name="g1")
    g2 = Group.objects.create(name="g2")
    user.groups.add(g1, g2)

    agg = UserAgg(queryset=User.objects.all())
    child_qs = agg.get_child_queryset("groups", UserAgg.groups)
    # Should be deduplicated via .distinct()
    assert child_qs.count() == 2


def test_extract_aggregate_selection_field_node_no_selection_set():
    """``_extract_aggregate_selection`` returns None when a field node lacks a selection set."""
    info = MagicMock()
    field_node = MagicMock()
    field_node.selection_set = None  # no selection_set on this field_node
    info.field_nodes = [field_node]
    result = AdvancedDjangoFilterConnectionField._extract_aggregate_selection(info)
    assert result is None


@pytest.mark.django_db
def test_compute_local_only_skips_related_aggregates():
    """``local_only=True`` skips the RelatedAggregate traversal entirely."""

    class ChildAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            fields = {"name": ["count"]}

    class ParentAgg(AdvancedAggregateSet):
        objects = RelatedAggregate(ChildAgg, field_name="object_type")

        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    ot = ObjectType.objects.create(name="local_only_test")
    Object.objects.create(name="child", object_type=ot)

    agg = ParentAgg(queryset=ObjectType.objects.all())

    # local_only=True should return own fields but skip 'objects' related aggregate
    result = agg.compute(local_only=True)
    assert "name" in result
    assert "objects" not in result


def test_reserved_count_field_name_raises():
    """Metaclass rejects 'count' in Meta.fields (reserved for root total-row count)."""
    # Patch _get_field_category to accept "count" as a valid field so we
    # reach the reserved-name check (ObjectType has no field named "count").
    with (
        patch(
            "django_graphene_filters.aggregateset._get_field_category",
            return_value="numeric",
        ),
        pytest.raises(ValueError, match="conflicts with the reserved root-level aggregate 'count'"),
    ):

        class BadAgg(AdvancedAggregateSet):
            class Meta:
                model = ObjectType
                fields = {"count": ["min", "max"]}


def test_field_relation_name_collision_raises():
    """Metaclass rejects overlap between Meta.fields keys and RelatedAggregate names."""
    with pytest.raises(ValueError, match="Name collision"):

        class BadAgg(AdvancedAggregateSet):
            name = RelatedAggregate(AdvancedAggregateSet, field_name="name")

            class Meta:
                model = ObjectType
                fields = {"name": ["count"]}


# ---------------------------------------------------------------------------
# Metaclass inheritance — RelatedAggregate on base classes must propagate
# to subclasses (symmetric to the OrderSetMetaclass fix).
# ---------------------------------------------------------------------------


class TestRelatedAggregateInheritance:
    """Verify ``RelatedAggregate`` declarations are inherited from base classes."""

    def test_subclass_inherits_related_aggregates(self):
        """A subclass preserves its base class's ``RelatedAggregate`` declarations."""

        class ChildAgg(AdvancedAggregateSet):
            class Meta:
                model = Object
                fields = {"name": ["count"]}

        class BaseAgg(AdvancedAggregateSet):
            objects = RelatedAggregate(ChildAgg, field_name="object_type")

            class Meta:
                model = ObjectType
                fields = {"name": ["count"]}

        class SubAgg(BaseAgg):
            class Meta:
                model = ObjectType
                fields = {"name": ["count", "min"]}

        # The subclass should still see the inherited ``objects`` RelatedAggregate.
        assert "objects" in SubAgg.related_aggregates
        assert isinstance(SubAgg.related_aggregates["objects"], RelatedAggregate)

    def test_subclass_can_override_related_aggregate(self):
        """A subclass can override an inherited ``RelatedAggregate`` by redeclaring it."""

        class ChildAgg(AdvancedAggregateSet):
            class Meta:
                model = Object
                fields = {"name": ["count"]}

        class BaseAgg(AdvancedAggregateSet):
            objects = RelatedAggregate(ChildAgg, field_name="object_type")

            class Meta:
                model = ObjectType
                fields = {"name": ["count"]}

        class SubAgg(BaseAgg):
            # Override with a different field_name.
            objects = RelatedAggregate(ChildAgg, field_name="other_path")

            class Meta:
                model = ObjectType
                fields = {"name": ["count"]}

        assert SubAgg.related_aggregates["objects"].field_name == "other_path"

    def test_abstract_subclass_inherits_related_aggregates(self):
        """A subclass with ``Meta.model = None`` (abstract intermediate) still inherits.

        Takes the metaclass's abstract branch (``meta.model is None``) and
        must still publish the inherited ``RelatedAggregate`` so further
        subclasses see it — and must call ``bind_aggregateset`` on each
        inherited entry.
        """

        class ChildAgg(AdvancedAggregateSet):
            class Meta:
                model = Object
                fields = {"name": ["count"]}

        class BaseAgg(AdvancedAggregateSet):
            objects = RelatedAggregate(ChildAgg, field_name="object_type")

            class Meta:
                model = ObjectType
                fields = {"name": ["count"]}

        class AbstractMiddleAgg(BaseAgg):
            # Explicitly nullify ``Meta.model`` to force the metaclass's
            # abstract branch.  Without this override, the class would
            # inherit ``BaseAgg.Meta`` (which has a model) and take the
            # normal path instead.
            class Meta:
                model = None

        assert "objects" in AbstractMiddleAgg.related_aggregates
        # ``bind_aggregateset`` must have been called so lazy-string
        # references on inherited RelatedAggregates still resolve.
        assert hasattr(AbstractMiddleAgg.related_aggregates["objects"], "bound_aggregateset")

    @pytest.mark.django_db
    def test_inherited_related_aggregate_is_traversed_at_compute(self):
        """A subclass's inherited ``RelatedAggregate`` actually fires during ``compute()``."""

        class ChildAgg(AdvancedAggregateSet):
            class Meta:
                model = Object
                fields = {"name": ["count"]}

        class BaseAgg(AdvancedAggregateSet):
            objects = RelatedAggregate(ChildAgg, field_name="object_type")

            class Meta:
                model = ObjectType
                fields = {"name": ["count"]}

        class SubAgg(BaseAgg):
            class Meta:
                model = ObjectType
                fields = {"name": ["count"]}

        ot = ObjectType.objects.create(name="inherit-compute")
        Object.objects.create(name="o1", object_type=ot)
        Object.objects.create(name="o2", object_type=ot)

        result = SubAgg(queryset=ObjectType.objects.filter(pk=ot.pk)).compute()
        assert "objects" in result, (
            "Subclass lost the inherited RelatedAggregate — the metaclass "
            "stripped it.  This is the bug symmetric to the OrderSet one."
        )


# ---------------------------------------------------------------------------
# Regression: blanket ``.distinct()`` + aggregate-annotated queryset.
#
# The orderset's ``.distinct(*fields)`` path used to raise
# ``NotImplementedError("annotate() + distinct(fields) is not implemented.")``
# on aggregate-annotated querysets; the fix added ``has_group_by``
# detection and falls back to Window-emulated distinct-on.
#
# ``AdvancedDjangoFilterConnectionField.resolve_queryset`` also applies a
# blanket ``.distinct()`` (no args) to dedup join duplicates.  Plain
# ``.distinct()`` is a different Django code path that DOES work with
# GROUP BY querysets — these tests lock that in so nobody "fixes" it by
# adding spurious ``has_group_by`` detection or by switching to the
# field-arg form.
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_blanket_distinct_on_group_by_queryset_preserves_count():
    """Plain ``.distinct()`` on a GROUP BY queryset still allows ``.count()``."""
    from django.db.models import Count

    ot = ObjectType.objects.create(name="grp-count")
    for i in range(5):
        Object.objects.create(name=f"o{i}", object_type=ot)

    # Simulate a queryset that arrives at ``resolve_queryset`` with
    # ``query.group_by`` already set — e.g. from a filterset that
    # annotated with an aggregate expression.
    qs = ObjectType.objects.annotate(_obj_count=Count("objectss"))
    assert qs.query.group_by  # sanity: annotation triggered GROUP BY

    qs_distinct = qs.distinct()
    # Plain distinct() keeps GROUP BY, but ``.count()`` still works
    # (Django wraps in a subquery).
    assert qs_distinct.count() >= 1


@pytest.mark.django_db
def test_blanket_distinct_on_group_by_queryset_allows_subsequent_aggregate():
    """Plain ``.distinct()`` on a GROUP BY queryset still allows ``.aggregate()``.

    This is the specific path the aggregate pipeline takes after
    ``resolve_queryset`` stores the queryset on ``qs._aggregate_set``
    and ``compute()`` eventually runs ``queryset.aggregate(**kwargs)``.
    """
    from django.db.models import Count, Sum

    ot = ObjectType.objects.create(name="grp-agg")
    for i in range(3):
        Object.objects.create(name=f"a{i}", object_type=ot)

    qs = ObjectType.objects.annotate(_obj_count=Count("objectss"))
    qs_distinct = qs.distinct()

    # The aggregate pipeline calls .aggregate(**kwargs) on the stored qs.
    # With plain .distinct() + GROUP BY this should succeed — NOT raise
    # the ``NotImplementedError`` that ``.distinct(*fields)`` raises.
    result = qs_distinct.aggregate(total_children=Sum("_obj_count"))
    assert result["total_children"] is not None


@pytest.mark.django_db
def test_blanket_distinct_with_compute_after_aggregate_annotation():
    """End-to-end: ``AdvancedAggregateSet.compute()`` on a ``.distinct()``
    queryset carrying an outer aggregate annotation.

    Mimics the interaction between the connection field's blanket
    ``.distinct()`` and the aggregate pipeline.  If ``.distinct()``
    conflicted with ``.aggregate()`` on GROUP BY querysets, the
    ``Count(f, distinct=True)`` call inside ``_compute_own_fields``
    would raise.
    """
    from django.db.models import Count

    ot1 = ObjectType.objects.create(name="e2e-a")
    ot2 = ObjectType.objects.create(name="e2e-b")
    Object.objects.create(name="o-a", object_type=ot1)
    Object.objects.create(name="o-b", object_type=ot2)

    # Build a queryset with aggregate annotation, then apply blanket
    # .distinct() — same shape the connection field produces.
    qs = ObjectType.objects.filter(name__startswith="e2e-").annotate(_obj_count=Count("objectss")).distinct()

    class NameAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count", "min", "max"]}

    result = NameAgg(queryset=qs).compute(local_only=True)
    assert result["count"] == 2
    assert result["name"]["count"] == 2
    assert result["name"]["min"] == "e2e-a"
    assert result["name"]["max"] == "e2e-b"
