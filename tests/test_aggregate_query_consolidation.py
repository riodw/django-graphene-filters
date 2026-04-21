"""Tests for the query-consolidation refactor in `aggregateset.py`.

Covers the behavioural guarantees spelled out in
``docs/spec-async_and_query_consolidation.md``:

1. **Consolidation** — every DB-level stat for every field rides in one
   ``.aggregate(**kwargs)`` call, not one-per-stat.
2. **Memoization** — ``_fetch_values()`` runs once per field that has any
   Python stats, regardless of how many Python stats that field requests.
3. **Semantic parity** — the DB and Python paths return the same dict shape
   and values the library has always produced.
4. **Async** — ``acompute()`` returns byte-identical output to
   ``compute()`` for the same selection.
"""

import asyncio
from unittest.mock import patch

import pytest
from cookbook.recipes.models import Object, ObjectType
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_graphene_filters.aggregateset import (
    DB_AGGREGATES,
    DB_NATIVE_PERCENTILE_STATS,
    PYTHON_STATS,
    SPECIAL_STATS,
    AdvancedAggregateSet,
    RelatedAggregate,
    _alias,
    _py_median_from_values,
    _py_mode_from_values,
    _py_stdev_from_values,
    _py_variance_from_values,
)
from django_graphene_filters.conf import settings as pkg_settings

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _seed_objects(n: int = 6) -> ObjectType:
    """Seed one ObjectType with n Objects having distinct names and ages."""
    ot = ObjectType.objects.create(name=f"cat-{n}", is_private=False)
    for i in range(n):
        Object.objects.create(
            name=f"obj-{i}",
            description=f"desc-{i}",
            object_type=ot,
            is_private=False,
        )
    return ot


# ---------------------------------------------------------------------------
# 1. Query-count consolidation
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_consolidated_db_aggregates_emit_single_aggregate_query():
    """All DB-level stats for all fields collapse into one .aggregate() call.

    The previous implementation issued one query per (field, stat) pair;
    the consolidated path runs one .aggregate(**kwargs) plus the root
    .count() — so a five-stat config executes exactly two queries.
    """
    _seed_objects(6)

    class MultiStatAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            fields = {
                "name": ["count", "min", "max"],
                "description": ["count", "min", "max"],
            }

    agg = MultiStatAgg(queryset=Object.objects.all())

    with CaptureQueriesContext(connection) as ctx:
        result = agg.compute(local_only=True)

    # 1 for the root .count(), 1 for the consolidated .aggregate().
    assert len(ctx.captured_queries) == 2, (
        f"Expected 2 queries (root count + consolidated aggregate), "
        f"got {len(ctx.captured_queries)}:\n" + "\n".join(q["sql"] for q in ctx.captured_queries)
    )
    # Sanity: results still populate correctly.
    assert result["count"] == 6
    assert result["name"]["count"] == 6
    assert result["description"]["count"] == 6


@pytest.mark.django_db
def test_python_stats_fetch_values_once_per_field():
    """Four Python stats on one field → one _fetch_values() call, not four."""
    _seed_objects(5)

    class PyStatsAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            # All four live in PYTHON_STATS; on SQLite this is 4 Python
            # stats sharing one values fetch.  On PostgreSQL, stdev and
            # variance get folded into the native .aggregate() call,
            # leaving median and mode to share the fetch (still 1 fetch).
            fields = {"id": ["median", "mode", "stdev", "variance"]}

    agg = PyStatsAgg(queryset=Object.objects.all())

    with patch(
        "django_graphene_filters.aggregateset._fetch_values",
        wraps=lambda qs, f, limit=None: list(
            qs.exclude(**{f: None}).values_list(f, flat=True)[: limit or 10000]
        ),
    ) as spy:
        agg.compute(local_only=True)

    # Memoization guarantee: one fetch per field, regardless of stat count.
    fetch_calls_for_id = [c for c in spy.call_args_list if c.args[1] == "id"]
    assert len(fetch_calls_for_id) <= 1, (
        f"Expected ≤1 _fetch_values call for 'id', got {len(fetch_calls_for_id)}: {fetch_calls_for_id}"
    )


@pytest.mark.django_db
def test_selection_set_subsetting_honours_consolidation():
    """Selection-set gating shrinks the .aggregate() call — no wasted work.

    When only `min` is requested, the consolidated query issues a single
    aggregate kwarg (not the full config).
    """
    _seed_objects(4)

    class SubsetAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            # `id` is numeric (AutoField) → supports count / min / max / sum.
            fields = {"id": ["count", "min", "max", "sum"]}

    agg = SubsetAgg(queryset=Object.objects.all())

    # Build a mock selection set that only requests `min`.
    class _Sel:
        def __init__(self, name, subs=None):
            self.name = type("N", (), {"value": name})()
            self.selection_set = type("SS", (), {"selections": [_Sel(s) for s in subs]})() if subs else None

    root = type("Root", (), {"selections": [_Sel("id", ["min"])]})()

    with CaptureQueriesContext(connection) as ctx:
        result = agg.compute(selection_set=root, local_only=True)

    # Two queries (root .count() + consolidated .aggregate()).
    assert len(ctx.captured_queries) == 2
    # The consolidated aggregate SQL must contain MIN and nothing else —
    # the planner only enqueued a single alias (the counter-based
    # ``_agg_0``), so SUM / MAX / AVG should NOT appear.  Identify the
    # aggregate query by its ``_agg_`` alias prefix (distinguishing it
    # from the root COUNT(*) query).
    agg_sql = next(q["sql"] for q in ctx.captured_queries if "_agg_" in q["sql"])
    sql_upper = agg_sql.upper()
    assert "MIN(" in sql_upper
    assert "SUM(" not in sql_upper
    assert "MAX(" not in sql_upper
    assert "AVG(" not in sql_upper
    assert result["id"] == {"min": min(Object.objects.values_list("id", flat=True))}


# ---------------------------------------------------------------------------
# 2. Semantic parity (equivalence with pre-refactor behaviour)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_count_distinct_matches_subquery_form():
    """New `Count(f, distinct=True)` matches old subquery form semantically.

    The replaced expression was
    ``qs.exclude(f=None).values(f).distinct().count()`` — both forms count
    distinct non-NULL values.  Verify against a dataset with duplicates.
    """
    ot = ObjectType.objects.create(name="dup", is_private=False)
    for name in ["a", "a", "b", "b", "c"]:
        Object.objects.create(name=name, object_type=ot, is_private=False)

    class DupAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            fields = {"name": ["count"]}

    agg = DupAgg(queryset=Object.objects.filter(object_type=ot))
    result = agg.compute(local_only=True)
    # 3 distinct names: a, b, c
    assert result["name"]["count"] == 3


@pytest.mark.django_db
def test_true_false_count_still_correct():
    """`true_count` / `false_count` via `Count("pk", filter=Q(...))` is correct."""
    ObjectType.objects.create(name="pub-a", is_private=False)
    ObjectType.objects.create(name="pub-b", is_private=False)
    ObjectType.objects.create(name="priv-a", is_private=True)

    class BoolAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"is_private": ["count", "true_count", "false_count"]}

    agg = BoolAgg(queryset=ObjectType.objects.all())
    result = agg.compute(local_only=True)
    assert result["is_private"]["true_count"] == 1
    assert result["is_private"]["false_count"] == 2


# ---------------------------------------------------------------------------
# 3. PostgreSQL-native stdev / variance
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pg_native_stdev_variance_skip_python_path():
    """On PostgreSQL, stdev / variance route through DB_NATIVE_PERCENTILE_STATS.

    The marker: ``_fetch_values`` is NOT called for a PG-only native stat.
    Skipped on non-PG backends because the Python fallback still wins there.
    """
    if not pkg_settings.IS_POSTGRESQL:
        pytest.skip("PG-native stdev / variance only active on PostgreSQL")

    _seed_objects(5)

    class NativeAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            fields = {"id": ["stdev", "variance"]}

    agg = NativeAgg(queryset=Object.objects.all())

    with patch("django_graphene_filters.aggregateset._fetch_values") as spy:
        result = agg.compute(local_only=True)

    spy.assert_not_called()
    assert result["id"]["stdev"] is not None
    assert result["id"]["variance"] is not None


# ---------------------------------------------------------------------------
# 4. Async acompute()
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_acompute_matches_compute_output():
    """acompute() returns byte-identical output to compute() for the same input."""
    _seed_objects(4)

    class ParityAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            fields = {
                "name": ["count", "min", "max"],
                "description": ["count", "min", "max"],
            }

    sync_agg = ParityAgg(queryset=Object.objects.all())
    sync_result = sync_agg.compute(local_only=True)

    async_agg = ParityAgg(queryset=Object.objects.all())
    async_result = asyncio.run(async_agg.acompute(local_only=True))

    assert async_result == sync_result


# ---------------------------------------------------------------------------
# 5. Registry shape + backward compat
# ---------------------------------------------------------------------------


def test_registry_categories_are_disjoint_except_python_vs_pg_native():
    """Each stat appears in exactly one of DB_AGGREGATES / PYTHON_STATS /
    SPECIAL_STATS — with the documented exception that stdev / variance
    may appear in both PYTHON_STATS (fallback) and DB_NATIVE_PERCENTILE_STATS
    (PG path).
    """
    db = set(DB_AGGREGATES)
    py = set(PYTHON_STATS)
    sp = set(SPECIAL_STATS)
    native = set(DB_NATIVE_PERCENTILE_STATS)

    assert db.isdisjoint(py)
    assert db.isdisjoint(sp)
    assert py.isdisjoint(sp)
    # PG-native stats are a subset of PYTHON_STATS (they override it on PG).
    assert native.issubset(py), (
        f"DB_NATIVE_PERCENTILE_STATS ({native}) must be a subset of "
        f"PYTHON_STATS ({py}) — the PG path overrides the Python fallback."
    )


# ---------------------------------------------------------------------------
# 6. Python-stat `_from_values` helper edge cases
# ---------------------------------------------------------------------------


def test_py_median_from_values_empty():
    """Median of an empty list returns None (matches old `_py_median`)."""
    assert _py_median_from_values([]) is None


def test_py_mode_from_values_empty_and_statistics_error():
    """Mode of an empty list returns None; StatisticsError path also returns None."""
    assert _py_mode_from_values([]) is None

    # Force StatisticsError by feeding statistics.mode values it can't mode
    # reliably — an empty list triggers the early-return, so patch
    # `statistics.mode` to raise and confirm the except branch hits.
    with patch(
        "django_graphene_filters.aggregateset.statistics.mode",
        side_effect=__import__("statistics").StatisticsError("boom"),
    ):
        assert _py_mode_from_values([1, 2, 3]) is None


def test_py_stdev_from_values_insufficient_data():
    """stdev of <2 values returns None (can't compute sample stdev)."""
    assert _py_stdev_from_values([]) is None
    assert _py_stdev_from_values([42]) is None
    # 2+ values → non-None
    assert _py_stdev_from_values([1, 2, 3]) is not None


def test_py_variance_from_values_insufficient_data():
    """variance of <2 values returns None."""
    assert _py_variance_from_values([]) is None
    assert _py_variance_from_values([42]) is None
    assert _py_variance_from_values([1, 2, 3]) is not None


# ---------------------------------------------------------------------------
# 7. acompute() with RelatedAggregates — exercises asyncio.gather fan-out
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_acompute_with_related_aggregates_matches_sync():
    """acompute() over RelatedAggregates returns the same shape as compute()."""
    ot = ObjectType.objects.create(name="rel-parent", is_private=False)
    for i in range(3):
        Object.objects.create(name=f"child-{i}", object_type=ot, is_private=False)

    class ObjectAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            fields = {"name": ["count", "min", "max"]}

    class TypeAgg(AdvancedAggregateSet):
        # `field_name` is the FK column on the TARGET (Object) that points
        # back to the source (ObjectType), not the reverse-accessor name.
        objects = RelatedAggregate(ObjectAgg, field_name="object_type")

        class Meta:
            model = ObjectType
            fields = {"name": ["count", "min", "max"]}

    # Sync result
    sync_result = TypeAgg(queryset=ObjectType.objects.filter(pk=ot.pk)).compute()

    # Async result
    async_result = asyncio.run(TypeAgg(queryset=ObjectType.objects.filter(pk=ot.pk)).acompute())

    assert async_result == sync_result
    # Cross-check shape: own-field + related fan-out both populated.
    assert "name" in async_result
    assert "objects" in async_result
    assert async_result["objects"]["name"]["count"] == 3


@pytest.mark.django_db(transaction=True)
def test_acompute_skips_unrequested_related_aggregates():
    """A RelatedAggregate omitted from the selection_set is not traversed."""
    ot = ObjectType.objects.create(name="skip-rel", is_private=False)
    Object.objects.create(name="skip-child", object_type=ot, is_private=False)

    class ObjectAgg(AdvancedAggregateSet):
        class Meta:
            model = Object
            fields = {"name": ["count"]}

    class TypeAggWithUnusedRel(AdvancedAggregateSet):
        objects = RelatedAggregate(ObjectAgg, field_name="object_type")

        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    # Build a selection_set that only picks `name` — omitting `objects`
    # exercises the `rel_name not in requested → continue` branch.
    class _Sel:
        def __init__(self, name, subs=None):
            self.name = type("N", (), {"value": name})()
            self.selection_set = type("SS", (), {"selections": [_Sel(s) for s in subs]})() if subs else None

    root = type("Root", (), {"selections": [_Sel("name", ["count"])]})()

    result = asyncio.run(
        TypeAggWithUnusedRel(queryset=ObjectType.objects.filter(pk=ot.pk)).acompute(selection_set=root)
    )

    assert "name" in result
    assert "objects" not in result  # skipped because not requested


# ---------------------------------------------------------------------------
# 8. Review-fix: `_alias()` collision + async resolver dispatch
# ---------------------------------------------------------------------------


def test_alias_counter_is_injective():
    """Counter-based `_alias()` never produces duplicate strings.

    Regression for the collision in the prior
    ``f"_agg_{field}_{stat}"`` scheme — e.g. ``(field="x_true",
    stat="count")`` and ``(field="x", stat="true_count")`` both
    encoded to ``_agg_x_true_count``.  The counter scheme is injective
    by construction regardless of any ``(field, stat)`` input.
    """
    assert _alias(0) != _alias(1)
    assert len({_alias(i) for i in range(1000)}) == 1000


@pytest.mark.django_db
def test_planner_assigns_unique_alias_per_stat_even_with_overlapping_names():
    """All DB-level stats reach ``.aggregate()`` under distinct aliases.

    The planner walks every requested ``(field, stat)`` pair and emits
    a fresh counter-based alias.  Verifies by capturing the generated
    SQL and counting distinct ``AS "_agg_N"`` occurrences.
    """
    ObjectType.objects.create(name="ba", is_private=False)
    ObjectType.objects.create(name="bb", is_private=True)

    class MultiStatMixedAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            # 3 + 3 = 6 DB-level stats in one consolidated .aggregate().
            fields = {
                "name": ["count", "min", "max"],
                "is_private": ["count", "true_count", "false_count"],
            }

    agg = MultiStatMixedAgg(queryset=ObjectType.objects.all())

    with CaptureQueriesContext(connection) as ctx:
        result = agg.compute(local_only=True)

    # The consolidated aggregate query carries every alias; locate by prefix.
    agg_sql = next(q["sql"] for q in ctx.captured_queries if "_agg_" in q["sql"])

    import re

    # Match `_agg_N` where N is any integer, not the old field-encoded form.
    aliases = re.findall(r"_agg_\d+", agg_sql)
    assert len(aliases) >= 6, f"expected ≥6 alias occurrences in SQL, got {aliases}"
    assert len(set(aliases)) == len(aliases), f"duplicate aliases in SQL: {aliases}"

    # Sanity: every stat actually resolved to a correct value.
    assert result["name"]["count"] == 2
    assert result["is_private"]["count"] == 2  # two distinct values
    assert result["is_private"]["true_count"] == 1
    assert result["is_private"]["false_count"] == 1


@pytest.mark.django_db
def test_resolve_aggregates_sync_context_returns_dict():
    """In a sync resolver chain, nested `resolve_aggregates` returns a dict.

    Verifies the fallback branch of the async-dispatch logic: when no
    event loop is running, the resolver calls ``compute(local_only=True)``
    and returns the result directly.
    """
    import graphene

    from django_graphene_filters.object_type import AdvancedDjangoObjectType

    class _SyncDispAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    class _SyncDispatchNode(AdvancedDjangoObjectType):
        class Meta:
            model = ObjectType
            interfaces = (graphene.relay.Node,)
            fields = "__all__"
            aggregate_class = _SyncDispAgg

    ObjectType.objects.create(name="sync-a")
    ObjectType.objects.create(name="sync-b")

    resolve = _SyncDispatchNode._meta.connection.resolve_aggregates
    root = type("R", (), {"iterable": ObjectType.objects.all()})()
    info = type("I", (), {"context": None})()

    result = resolve(root, info)
    assert isinstance(result, dict)
    assert result["count"] >= 2


@pytest.mark.django_db(transaction=True)
def test_resolve_aggregates_returns_coroutine_when_ASYNC_AGGREGATES_enabled():
    """``resolve_aggregates`` returns a coroutine only when explicitly opted-in.

    Regression for the two Medium items in ``docs/review.md``:

    1. The resolver must actually dispatch to ``acompute()`` (it didn't
       before — the sync path precomputed aggregates and the async
       branch was unreachable at the root level).
    2. The dispatch signal must be an explicit setting, not a
       ``asyncio.get_running_loop()`` probe — a caller inside
       ``asyncio.run(...)`` invoking the schema synchronously would
       otherwise get back an unawaited coroutine.
    """
    import graphene
    from django.test import override_settings

    from django_graphene_filters.object_type import AdvancedDjangoObjectType

    class _AsyncDispAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    class _AsyncDispatchNode(AdvancedDjangoObjectType):
        class Meta:
            model = ObjectType
            interfaces = (graphene.relay.Node,)
            fields = "__all__"
            aggregate_class = _AsyncDispAgg

    ObjectType.objects.create(name="async-a")
    ObjectType.objects.create(name="async-b")

    resolve = _AsyncDispatchNode._meta.connection.resolve_aggregates

    # Opt-out (default): sync call returns a dict synchronously.
    root = type("R", (), {"iterable": ObjectType.objects.all()})()
    info = type("I", (), {"context": None})()
    returned = resolve(root, info)
    assert isinstance(returned, dict), "ASYNC_AGGREGATES defaults to False — resolver must return a dict."
    assert returned["count"] >= 2

    # Opt-in: ``ASYNC_AGGREGATES = True`` — resolver returns a coroutine
    # that Graphene's async executor awaits.  We construct the root
    # (which touches the ORM) OUTSIDE the asyncio loop to avoid the
    # sync-in-async guard — only ``resolve()`` and the awaited coroutine
    # need to run inside the loop.
    with override_settings(DJANGO_GRAPHENE_FILTERS={"ASYNC_AGGREGATES": True}):
        root = type("R", (), {"iterable": ObjectType.objects.all()})()
        info = type("I", (), {"context": None})()
        returned = resolve(root, info)
        assert asyncio.iscoroutine(returned), (
            "With ASYNC_AGGREGATES=True, resolve_aggregates must return a "
            "coroutine so Graphene's async executor awaits acompute()."
        )
        final = asyncio.run(returned)
        assert isinstance(final, dict)
        assert final["count"] >= 2


@pytest.mark.django_db
def test_resolve_aggregates_uses_stored_aggregate_set_for_root_level():
    """Root-level connections use the pre-built aggregate set on the queryset.

    Regression for the first Medium item in ``docs/review.md``:
    ``AdvancedDjangoFilterConnectionField.resolve_queryset`` now defers
    ``compute()`` by stashing ``_aggregate_set`` and
    ``_aggregate_selection`` on the queryset — the resolver must consume
    them so the root path honours:

    * the extracted GraphQL selection (not an implicit local-only subset);
    * ``RelatedAggregate`` traversal (i.e. NOT ``local_only=True``);
    * the same async dispatch as the nested path.
    """
    import graphene

    from django_graphene_filters.object_type import AdvancedDjangoObjectType

    class _RootAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    class _RootNode(AdvancedDjangoObjectType):
        class Meta:
            model = ObjectType
            interfaces = (graphene.relay.Node,)
            fields = "__all__"
            aggregate_class = _RootAgg

    ObjectType.objects.create(name="root-a")
    ObjectType.objects.create(name="root-b")

    resolve = _RootNode._meta.connection.resolve_aggregates

    # Simulate what resolve_queryset does: build the agg set, stash it
    # plus the extracted selection on the queryset, then let the resolver
    # run the full compute() (with RelatedAggregate fan-out, not
    # local_only) off the stored state.
    qs = ObjectType.objects.all()
    qs._aggregate_set = _RootAgg(queryset=qs, request=None)
    qs._aggregate_selection = None  # None → compute everything

    root = type("R", (), {"iterable": qs})()
    info = type("I", (), {"context": None})()

    result = resolve(root, info)
    assert isinstance(result, dict)
    assert result["count"] >= 2
    # The stored selection path populates the full config, not just root count.
    assert "name" in result
    assert result["name"]["count"] >= 2


@pytest.mark.django_db
def test_resolve_aggregates_uses_precomputed_when_present():
    """If the queryset carries precomputed aggregates, return them directly.

    The precomputation path in ``connection_field.resolve_queryset`` runs
    sync (graphene-django's resolver chain for connections is
    synchronous).  When it populates ``root.aggregates``, the nested
    resolver must short-circuit and not re-compute via sync or async.
    """
    import graphene

    from django_graphene_filters.object_type import AdvancedDjangoObjectType

    class _PreAgg(AdvancedAggregateSet):
        class Meta:
            model = ObjectType
            fields = {"name": ["count"]}

    class _PreNode(AdvancedDjangoObjectType):
        class Meta:
            model = ObjectType
            interfaces = (graphene.relay.Node,)
            fields = "__all__"
            aggregate_class = _PreAgg

    resolve = _PreNode._meta.connection.resolve_aggregates
    sentinel = {"count": 999, "name": {"count": 42}}
    root = type("R", (), {"aggregates": sentinel})()
    info = type("I", (), {"context": None})()

    result = resolve(root, info)
    assert result is sentinel
