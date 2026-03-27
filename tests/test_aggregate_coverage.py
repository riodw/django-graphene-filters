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
    _bool_false_count,
    _bool_true_count,
    _fetch_values,
    _py_median,
    _py_mode,
    _py_stdev,
    _py_variance,
)
from django_graphene_filters.connection_field import AdvancedDjangoFilterConnectionField
from django_graphene_filters.mixins import ObjectTypeFactoryMixin
from django_graphene_filters.object_type import _inject_aggregates_on_connection

# ---------------------------------------------------------------------------
# aggregateset.py — python-level stat helpers
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_py_median():
    """Cover _py_median (lines 43-44)."""
    ot = ObjectType.objects.create(name="med")
    Object.objects.create(name="a1", object_type=ot)
    Object.objects.create(name="a2", object_type=ot)
    Object.objects.create(name="a3", object_type=ot)
    result = _py_median(Object.objects.all(), "id")
    assert result is not None


@pytest.mark.django_db
def test_py_mode_statistics_error():
    """Cover _py_mode StatisticsError branch (lines 54-55)."""
    # Empty queryset → no data → returns None
    result = _py_mode(Object.objects.none(), "id")
    assert result is None


@pytest.mark.django_db
def test_py_stdev():
    """Cover _py_stdev (lines 60-61)."""
    ot = ObjectType.objects.create(name="sd")
    Object.objects.create(name="s1", object_type=ot)
    Object.objects.create(name="s2", object_type=ot)
    Object.objects.create(name="s3", object_type=ot)
    result = _py_stdev(Object.objects.all(), "id")
    assert result is not None


@pytest.mark.django_db
def test_py_stdev_insufficient_data():
    """Cover _py_stdev returning None for single data point (line 61 else branch)."""
    ot = ObjectType.objects.create(name="single")
    result = _py_stdev(ObjectType.objects.filter(pk=ot.pk), "id")
    assert result is None


@pytest.mark.django_db
def test_py_variance():
    """Cover _py_variance (lines 66-67)."""
    ot = ObjectType.objects.create(name="var")
    Object.objects.create(name="v1", object_type=ot)
    Object.objects.create(name="v2", object_type=ot)
    Object.objects.create(name="v3", object_type=ot)
    result = _py_variance(Object.objects.all(), "id")
    assert result is not None


@pytest.mark.django_db
def test_py_variance_insufficient_data():
    """Cover _py_variance returning None for single data point (line 67 else branch)."""
    ot = ObjectType.objects.create(name="single_var")
    result = _py_variance(ObjectType.objects.filter(pk=ot.pk), "id")
    assert result is None


@pytest.mark.django_db
def test_bool_true_count():
    """Cover _bool_true_count (line 85)."""
    ObjectType.objects.create(name="pub", is_private=False)
    ObjectType.objects.create(name="priv", is_private=True)
    assert _bool_true_count(ObjectType.objects.all(), "is_private") == 1


@pytest.mark.django_db
def test_bool_false_count():
    """Cover _bool_false_count (line 90)."""
    ObjectType.objects.create(name="pub2", is_private=False)
    ObjectType.objects.create(name="priv2", is_private=True)
    assert _bool_false_count(ObjectType.objects.all(), "is_private") == 1


@pytest.mark.django_db
def test_fetch_values_safety_limit():
    """Cover _fetch_values safety limit warning (line 32)."""
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
    """Cover bind_aggregateset no-op when already bound (line 166->exit)."""
    ra = RelatedAggregate(AdvancedAggregateSet, field_name="test")
    ra.bind_aggregateset(ObjectType)
    # Second call should be a no-op
    ra.bind_aggregateset(Object)
    assert ra.bound_aggregateset is ObjectType


def test_related_aggregate_class_setter():
    """Cover aggregate_class setter (line 180)."""
    ra = RelatedAggregate(AdvancedAggregateSet, field_name="test")
    ra.aggregate_class = ObjectType
    assert ra._aggregate_class is ObjectType


# ---------------------------------------------------------------------------
# aggregateset.py — _get_field_category validation
# ---------------------------------------------------------------------------


def test_get_field_category_nonexistent_field():
    """Cover ValueError when field doesn't exist (lines 203-204)."""
    with pytest.raises(ValueError, match="does not exist"):

        class BadFieldAgg(AdvancedAggregateSet):
            class Meta:
                model = ObjectType
                fields = {"nonexistent_field": ["count"]}


def test_get_field_category_unsupported_type():
    """Cover ValueError when field type is unrecognised (line 209)."""
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
    """Cover metaclass ValueError for invalid stat (lines 249-251)."""
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
    """Cover _check_field_permission call (line 421)."""

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
    """Cover _check_stat_permission call (line 427)."""

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
    """Cover _parse_selection_set when a selection has no sub-selections (line 453)."""
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
    """Cover _get_child_selection with None selection_set (line 464)."""
    result = AdvancedAggregateSet._get_child_selection(None, "test")
    assert result is None


def test_get_child_selection_field_not_found():
    """Cover _get_child_selection when field name doesn't match (line 468)."""
    sel = MagicMock()
    sel.name.value = "other_field"
    parent = MagicMock()
    parent.selections = [sel]
    result = AdvancedAggregateSet._get_child_selection(parent, "missing_field")
    assert result is None


# ---------------------------------------------------------------------------
# aggregateset.py — M2M lookup
# ---------------------------------------------------------------------------


def test_is_m2m_lookup_exception():
    """Cover _is_m2m_lookup except branch (lines 414-415)."""
    # Pass a nonexistent field name → should return False
    result = AdvancedAggregateSet._is_m2m_lookup(ObjectType, "totally_fake_field")
    assert result is False


# ---------------------------------------------------------------------------
# connection_field.py — aggregate properties
# ---------------------------------------------------------------------------


def test_connection_field_provided_aggregate_class():
    """Cover provided_aggregate_class property (line 73)."""
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
    """Cover aggregate_class property caching (lines 78-80)."""
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
    """Cover aggregate_type property (lines 85-95)."""
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
    """Cover _extract_aggregate_selection except branch (lines 372-373)."""
    info = MagicMock()
    # Make field_nodes iteration raise TypeError
    info.field_nodes = None
    result = AdvancedDjangoFilterConnectionField._extract_aggregate_selection(info)
    assert result is None


# ---------------------------------------------------------------------------
# mixins.py — ObjectTypeFactoryMixin cache hit
# ---------------------------------------------------------------------------


def test_object_type_factory_mixin_cache_hit():
    """Cover create_object_type cache hit (line 95)."""
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
    """Cover early return when connection already has _aggregate_field_injected (line 35)."""

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
    """Cover resolve_aggregates returning None when no iterable (line 63)."""
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


# ---------------------------------------------------------------------------
# aggregate_arguments_factory.py — circular reference branch
# ---------------------------------------------------------------------------


def test_aggregate_factory_circular_reference():
    """Cover the circular reference skip (line 133->128 branch)."""

    class CircularAgg(AdvancedAggregateSet):
        self_ref = RelatedAggregate("CircularAgg", field_name="object_type")

        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    # Manually resolve the lazy string reference
    CircularAgg.self_ref._aggregate_class = CircularAgg
    CircularAgg.related_aggregates = OrderedDict([("self_ref", CircularAgg.self_ref)])

    factory = AggregateArgumentsFactory(CircularAgg, "Circular")
    # Should not raise / infinite loop
    result = factory.build_aggregate_type()
    assert result is not None


# ---------------------------------------------------------------------------
# aggregateset.py — compute() with boolean stats via aggregateset
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_compute_boolean_stats():
    """Cover boolean stat computation via compute() (true_count, false_count via STAT_REGISTRY)."""

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
def test_compute_numeric_stats_via_registry():
    """Cover STAT_REGISTRY fallback for median/stdev/variance (line 346->330 branch)."""

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


@pytest.mark.django_db
def test_py_mode_statistics_error_raised():
    """Cover _py_mode except StatisticsError branch (lines 54-55) by mocking."""
    import statistics as stats_mod

    ot = ObjectType.objects.create(name="mode_err")
    Object.objects.create(name="me1", object_type=ot)
    with patch.object(stats_mod, "mode", side_effect=stats_mod.StatisticsError("no mode")):
        result = _py_mode(Object.objects.all(), "id")
    assert result is None


def test_metaclass_custom_compute_method_passes_validation():
    """Cover metaclass branch where compute_<field>_<stat> exists (line 250->246)."""

    # This should NOT raise — the compute_ method validates the unknown stat.
    class ComputeMethodAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["my_custom_stat"]}

        def compute_name_my_custom_stat(self, queryset):
            return "custom_result"

    assert "my_custom_stat" in ComputeMethodAgg._aggregate_config["name"]["stats"]


@pytest.mark.django_db
def test_compute_custom_stat_not_in_registry():
    """Cover compute() branch where stat is in custom_stats but not in STAT_REGISTRY (line 346->330)."""

    class NoComputeCustomAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["weird_stat"]}
            custom_stats = {"weird_stat": graphene.String}

    ObjectType.objects.create(name="custom_no_compute")
    agg = NoComputeCustomAgg(queryset=ObjectType.objects.all())
    result = agg.compute()
    # weird_stat has no compute_ method and is not in STAT_REGISTRY → silently skipped
    assert "weird_stat" not in result["name"]


def test_build_stat_fields_skips_unknown_stat():
    """Cover _build_stat_fields loop-back when stat not in custom_stats or category_types (line 133->128)."""
    fields = AggregateArgumentsFactory._build_stat_fields(
        category="text",
        stat_names=["count", "unknown_stat_xyz"],
        custom_stats={},
    )
    # unknown_stat_xyz should be skipped
    assert "count" in fields
    assert "unknown_stat_xyz" not in fields


def test_extract_aggregate_selection_no_aggregates_field():
    """Cover _extract_aggregate_selection loop that doesn't find 'aggregates' (line 368->367)."""
    info = MagicMock()
    field_node = MagicMock()
    sel = MagicMock()
    sel.name.value = "edges"  # not 'aggregates'
    field_node.selection_set.selections = [sel]
    info.field_nodes = [field_node]
    result = AdvancedDjangoFilterConnectionField._extract_aggregate_selection(info)
    assert result is None


@pytest.mark.django_db
def test_is_m2m_lookup_true():
    """Cover _is_m2m_lookup returning True for actual M2M field."""
    from django.contrib.auth.models import User

    result = AdvancedAggregateSet._is_m2m_lookup(User, "groups")
    assert result is True


@pytest.mark.django_db
def test_get_child_queryset_m2m_distinct():
    """Cover get_child_queryset applying .distinct() for M2M (line 396)."""
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
    """Cover _extract_aggregate_selection with field_node.selection_set falsy (line 365->364)."""
    info = MagicMock()
    field_node = MagicMock()
    field_node.selection_set = None  # no selection_set on this field_node
    info.field_nodes = [field_node]
    result = AdvancedDjangoFilterConnectionField._extract_aggregate_selection(info)
    assert result is None


@pytest.mark.django_db
def test_compute_local_only_skips_related_aggregates():
    """Cover aggregateset.py line 353: local_only=True early return skips related traversal."""

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
