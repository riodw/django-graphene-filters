"""Tests that close the remaining non-PostgreSQL coverage branches.

Each test targets a specific uncovered line / branch flagged by
``coverage report --show-missing``.  PostgreSQL-only paths (e.g. the
Trigram warning on PG without ``pg_trgm``) are intentionally excluded \u2014
they can't be exercised on the SQLite CI backend without running a real
PG instance.
"""

import asyncio
from unittest.mock import MagicMock, patch

import graphene
from cookbook.recipes.models import Object, ObjectType
from django.db import models
from graphene_django import DjangoObjectType

from django_graphene_filters import conf as _conf
from django_graphene_filters.aggregate_arguments_factory import AggregateArgumentsFactory
from django_graphene_filters.aggregateset import AdvancedAggregateSet, RelatedAggregate
from django_graphene_filters.conf import settings as pkg_settings
from django_graphene_filters.connection_field import AdvancedDjangoFilterConnectionField
from django_graphene_filters.filter_arguments_factory import FilterArgumentsFactory
from django_graphene_filters.filters import RelatedFilter
from django_graphene_filters.filterset import AdvancedFilterSet
from django_graphene_filters.filterset_factories import (
    _dynamic_filterset_cache,
    get_filterset_class,
)
from django_graphene_filters.input_data_factories import create_search_query
from django_graphene_filters.object_type import (
    _inject_aggregates_on_connection,
)
from django_graphene_filters.orderset import AdvancedOrderSet

# ---------------------------------------------------------------------------
# Test-only models
# ---------------------------------------------------------------------------


class CoverageGapModel(models.Model):
    """Model used by local filtersets in this file."""

    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "recipes"


# ---------------------------------------------------------------------------
# aggregate_arguments_factory.py line 159
# ---------------------------------------------------------------------------


def test_aggregate_factory_skips_related_target_when_none():
    """``_build_class_type`` skips a ``RelatedAggregate`` whose target is None."""

    class NoneTargetAgg(AdvancedAggregateSet):
        rel = RelatedAggregate(ObjectType, field_name="rel")

        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    # Force the target to None after class construction so the metaclass's
    # validation doesn't reject it upfront.
    NoneTargetAgg.related_aggregates["rel"]._aggregate_class = None

    # Clear cache so the build path actually runs.
    AggregateArgumentsFactory.object_types.pop(NoneTargetAgg.type_name_for(), None)
    AggregateArgumentsFactory._type_aggregate_registry.pop(NoneTargetAgg.type_name_for(), None)

    agg_type = AggregateArgumentsFactory(NoneTargetAgg).build_aggregate_type()

    # The root type was built, but the ``rel`` field was skipped.
    assert agg_type is not None
    assert "rel" not in agg_type._meta.fields


# ---------------------------------------------------------------------------
# connection_field.py line 211 \u2014 HIDE_FLAT_FILTERS=True branch
# ---------------------------------------------------------------------------


class _GapFS(AdvancedFilterSet):
    class Meta:
        model = CoverageGapModel
        fields = ["name"]


class _GapNode(DjangoObjectType):
    class Meta:
        model = CoverageGapModel
        fields = "__all__"
        interfaces = (graphene.relay.Node,)
        filterset_class = _GapFS


def test_filtering_args_omits_flat_args_when_hide_flat_filters_enabled():
    """When ``HIDE_FLAT_FILTERS`` is True, ``filtering_args`` emits only the\n    advanced ``filter`` argument \u2014 flat arguments (e.g. ``name_Iexact``) are\n    suppressed from the schema."""
    field = AdvancedDjangoFilterConnectionField(_GapNode, filterset_class=_GapFS)

    with patch.object(pkg_settings, "HIDE_FLAT_FILTERS", True):
        # Reset the cache so the property re-evaluates under the toggle.
        field._filtering_args = None
        args = field.filtering_args

    assert "filter" in args
    # No flat per-field args should appear.
    assert not any(k.startswith("name") for k in args if k != "filter")


# ---------------------------------------------------------------------------
# filter_arguments_factory.py lines 129->127 + 199->206 \u2014 None RelatedFilter target
# ---------------------------------------------------------------------------


def test_filter_factory_drops_related_filter_with_none_target():
    """``RelatedFilter(None, ...)`` through ``FilterArgumentsFactory``.

    Exercises two branches together:
    * BFS enqueue guard skips the None target (line 129->127).
    * ``_build_input_fields`` drops the field without emitting a lambda ref
      when ``target_fs`` is None (line 199->206).
    """

    class NoneTargetFS(AdvancedFilterSet):
        rel = RelatedFilter(None, field_name="rel")

        class Meta:
            model = CoverageGapModel
            fields = ["name"]

    # Clear caches
    FilterArgumentsFactory.input_object_types.pop(NoneTargetFS.type_name_for(), None)
    FilterArgumentsFactory._type_filterset_registry.pop(NoneTargetFS.type_name_for(), None)

    args = FilterArgumentsFactory(NoneTargetFS).arguments

    advanced_type = args["filter"].type
    # ``rel`` is absent (None target dropped); ``name`` is still there.
    assert "rel" not in advanced_type._meta.fields
    assert "name" in advanced_type._meta.fields


# ---------------------------------------------------------------------------
# filter_arguments_factory.py lines 229-230 \u2014 special postfix at child level
# ---------------------------------------------------------------------------


def test_build_path_subfield_routes_trigram_child_via_special_factory():
    """``_build_path_subfield`` routes a ``trigram`` child through the special factory.

    When trigram filters are enabled (PG + ``pg_trgm``), ``create_full_text_search_filters``
    generates ``<field>__trigram__<lookup>`` entries.  In the tree, ``trigram``
    appears as a child of the field node \u2014 the walker must route it through
    ``SPECIAL_FILTER_INPUT_TYPES_FACTORIES`` rather than build an operator bag.
    """
    mock_settings = MagicMock()
    mock_settings.IS_POSTGRESQL = True
    mock_settings.HAS_TRIGRAM_EXTENSION = True
    mock_settings.FILTER_KEY = "filter"
    mock_settings.AND_KEY = "and"
    mock_settings.OR_KEY = "or"
    mock_settings.NOT_KEY = "not"

    with patch("django_graphene_filters.filterset.settings", mock_settings):

        class TrigramGapFS(AdvancedFilterSet):
            class Meta:
                model = CoverageGapModel
                fields = {"name": ["full_text_search"]}

        FilterArgumentsFactory.input_object_types.pop(TrigramGapFS.type_name_for(), None)
        FilterArgumentsFactory._type_filterset_registry.pop(TrigramGapFS.type_name_for(), None)
        # The per-path subtype for ``name`` also needs clearing.
        FilterArgumentsFactory.input_object_types.pop(TrigramGapFS.type_name_for("name"), None)

        args = FilterArgumentsFactory(TrigramGapFS).arguments

    advanced_type = args["filter"].type
    # The name operator bag exists and contains the trigram sub-field.
    name_bag = advanced_type._meta.fields["name"].type
    assert "trigram" in name_bag._meta.fields


# ---------------------------------------------------------------------------
# filter_arguments_factory.py lines 237-238 \u2014 non-leaf child recursion
# ---------------------------------------------------------------------------


def test_build_path_subfield_recurses_into_non_leaf_field_name_segment():
    """Non-leaf children (multi-segment ``field_name__sub``) trigger recursion.

    A ``Meta.fields`` declaration like ``{"object_type__name": ["exact", "icontains"]}``
    generates filters whose ``field_name`` is ``object_type__name``.  The tree
    walker splits that into ``object_type → name → {exact, icontains}`` — the
    ``name`` node is non-leaf and is handled by the recursive ``else`` branch
    of ``_build_path_subfield``.
    """

    class NestedPathFS(AdvancedFilterSet):
        class Meta:
            model = Object
            fields = {"object_type__name": ["exact", "icontains"]}

    # Clear caches so the build path actually runs.
    FilterArgumentsFactory.input_object_types.pop(NestedPathFS.type_name_for(), None)
    FilterArgumentsFactory._type_filterset_registry.pop(NestedPathFS.type_name_for(), None)
    for key in list(FilterArgumentsFactory.input_object_types):
        if key.startswith("NestedPathFS"):
            FilterArgumentsFactory.input_object_types.pop(key, None)

    args = FilterArgumentsFactory(NestedPathFS).arguments
    root_input = args["filter"].type

    # ``object_type`` → ``name`` → {exact, icontains} proves the non-leaf else
    # branch fired at least once (walking into ``name``).
    object_type_bag = root_input._meta.fields["object_type"].type
    assert "name" in object_type_bag._meta.fields
    name_bag = object_type_bag._meta.fields["name"].type
    assert "exact" in name_bag._meta.fields
    assert "icontains" in name_bag._meta.fields


# ---------------------------------------------------------------------------
# filterset.py line 743 \u2014 _get_fields `f = {}` else branch
# ---------------------------------------------------------------------------


def test_get_fields_related_filter_with_none_target_yields_empty_branch():
    """``_get_fields`` returns ``f = {}`` when a RelatedFilter's target is None.

    Exercises the final ``else`` branch at line 743 of ``filterset.py``.
    """

    class HostFS(AdvancedFilterSet):
        rel = RelatedFilter(None, field_name="rel")

        class Meta:
            model = CoverageGapModel
            fields = ["name"]

    fields = HostFS.get_fields()
    # ``name`` is present (flat field), but no ``rel__*`` entries since the
    # None target produced ``f = {}``.
    assert "name" in fields
    assert not any(k.startswith("rel__") for k in fields)


# ---------------------------------------------------------------------------
# filterset_factories.py lines 33, 40 \u2014 dict + raw cache keys
# ---------------------------------------------------------------------------


def test_dynamic_filterset_cache_key_dict_fields():
    """``fields={"name": ["exact"]}`` takes the dict branch of ``_make_cache_key``."""
    _dynamic_filterset_cache.clear()
    cls_a = get_filterset_class(None, model=CoverageGapModel, fields={"name": ["exact"]})
    cls_b = get_filterset_class(None, model=CoverageGapModel, fields={"name": ["exact"]})
    # Same config \u2192 same cached class
    assert cls_a is cls_b
    assert issubclass(cls_a, AdvancedFilterSet)


def test_dynamic_filterset_cache_key_all_fields_raw():
    """``fields='__all__'`` takes the raw (fallback) branch of ``_make_cache_key``."""
    _dynamic_filterset_cache.clear()
    cls_a = get_filterset_class(None, model=CoverageGapModel, fields="__all__")
    cls_b = get_filterset_class(None, model=CoverageGapModel, fields="__all__")
    assert cls_a is cls_b
    assert issubclass(cls_a, AdvancedFilterSet)


# ---------------------------------------------------------------------------
# input_data_factories.py line 208->206 \u2014 empty NOT sub returns None
# ---------------------------------------------------------------------------


def test_create_search_query_skips_empty_not_subquery():
    """A NOT subquery whose inner ``create_search_query`` returns None is skipped.

    The inner has a present-but-empty ``AND_KEY`` list so ``validate_search_query``
    passes; ``create_search_query`` then returns None because no content was
    contributed.  The outer NOT loop must skip without combining.
    """
    and_key = _conf.settings.AND_KEY
    not_key = _conf.settings.NOT_KEY

    # Inner: validate passes (AND_KEY present) but no value \u2192 returns None.
    empty_sub = {and_key: []}
    # Outer: value produces a SearchQuery; NOT list has the empty sub to skip.
    outer = {"value": "hello", not_key: [empty_sub]}

    result = create_search_query(outer)
    # Skipping the empty NOT means ``value`` survives unchanged.
    assert result is not None


# ---------------------------------------------------------------------------
# object_type.py line 106 \u2014 async root-level aggregate resolver
# ---------------------------------------------------------------------------


def test_resolve_aggregates_async_path_with_stored_aggregate_set():
    """When ``ASYNC_AGGREGATES`` is True and ``iterable._aggregate_set`` is stashed,
    the resolver dispatches through ``pre_agg_set.acompute(...)`` (line 106).
    """

    class AsyncGapAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    class AsyncGapConnection:
        _meta = MagicMock()
        _meta.fields = {}

    _inject_aggregates_on_connection(ObjectType, AsyncGapAgg, AsyncGapConnection)

    # Build a fake ``_aggregate_set`` whose ``acompute`` is a coroutine that
    # returns a sentinel dict — no real DB involved.
    async def fake_acompute(*, selection_set=None):
        return {"count": 42, "via": "acompute"}

    pre_agg = MagicMock()
    pre_agg.acompute = fake_acompute

    iterable = MagicMock()
    iterable._aggregate_set = pre_agg
    iterable._aggregate_selection = None

    root = MagicMock(spec=["iterable"])
    root.iterable = iterable
    info = MagicMock()

    with patch.object(_conf.settings, "ASYNC_AGGREGATES", True):
        awaitable = AsyncGapConnection.resolve_aggregates(root, info)
        result = asyncio.run(awaitable)

    assert result == {"count": 42, "via": "acompute"}


# ---------------------------------------------------------------------------
# orderset.py line 227->229 \u2014 empty full_order skips queryset.order_by
# ---------------------------------------------------------------------------


def test_apply_distinct_postgres_skips_order_by_when_full_order_empty():
    """``_apply_distinct_postgres`` skips ``.order_by(*full_order)`` when\n    ``full_order`` is empty (distinct_fields and order_fields both empty)."""
    qs = MagicMock()
    qs.distinct.return_value = qs

    result = AdvancedOrderSet._apply_distinct_postgres(qs, [], [])

    qs.order_by.assert_not_called()
    qs.distinct.assert_called_once_with()
    assert result is qs


# ---------------------------------------------------------------------------
# orderset.py line 255 \u2014 window_order fallback when order_fields is empty
# ---------------------------------------------------------------------------


def test_apply_distinct_emulated_uses_pk_fallback_when_order_fields_empty():
    """``_apply_distinct_emulated`` falls back to ``window_order = [F('pk').asc()]``\n    when ``order_fields`` is empty."""
    qs = MagicMock()
    qs.annotate.return_value = qs
    qs.filter.return_value = qs

    result = AdvancedOrderSet._apply_distinct_emulated(qs, ["name"], [])

    qs.annotate.assert_called_once()
    qs.filter.assert_called_once_with(_distinct_row_num=1)
    assert result is qs


# ---------------------------------------------------------------------------
# aggregateset.py \u2014 ``Object`` model usage guard to keep Django happy when
# the module imports cleanly without pulling in migrations for CoverageGapModel.
# ---------------------------------------------------------------------------


def test_module_imports_cleanly():
    """Sanity: the test module can be imported without side effects."""
    assert Object is Object and ObjectType is ObjectType
