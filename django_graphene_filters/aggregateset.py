"""`AdvancedAggregateSet` class module.

Provides a declarative API for computing aggregate statistics on filtered
querysets, analogous to `AdvancedFilterSet` / `AdvancedOrderSet`.

Implements the query-consolidation plan in
``docs/spec-async_and_query_consolidation.md``: stats are classified
into four registries (``DB_AGGREGATES``, ``PYTHON_STATS``,
``SPECIAL_STATS``, ``DB_NATIVE_PERCENTILE_STATS``) and executed in
**plan → execute → assemble** phases so a single request hits the DB
with one consolidated ``.aggregate()`` call per queryset plus one value
fetch per Python-stat field (rather than one query per stat per field).
"""

import asyncio
import itertools
import logging
import statistics
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

from asgiref.sync import sync_to_async
from django.db.models import Aggregate, Avg, Count, Max, Min, Q, QuerySet, StdDev, Sum, Variance

from .aggregate_types import FIELD_CATEGORIES, VALID_STATS
from .conf import settings
from .mixins import ClassBasedTypeNameMixin, LazyRelatedClassMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Python-level helper functions
# ---------------------------------------------------------------------------


def _fetch_values(qs: QuerySet, field: str, limit: int | None = None) -> list:
    """Fetch non-null values for a field, respecting safety limits."""
    values_qs = qs.exclude(**{field: None}).values_list(field, flat=True)
    max_values = limit or getattr(settings, "AGGREGATE_MAX_VALUES", 10000)
    values = list(values_qs[:max_values])
    if len(values) == max_values:
        logger.warning(
            "Aggregate safety limit hit: fetched %d values for field '%s'. "
            "Stats computed on truncated dataset. Increase AGGREGATE_MAX_VALUES to raise the limit.",
            max_values,
            field,
        )
    return values


def _uniques(qs: QuerySet, field: str) -> list[dict[str, Any]]:
    """Return unique values with their counts."""
    max_uniques = getattr(settings, "AGGREGATE_MAX_UNIQUES", 1000)
    # Use _agg_val as the alias to avoid conflicting with model fields named 'value'
    rows = (
        qs.exclude(**{field: None})
        .values(_agg_val=models_F(field))
        .annotate(_agg_count=Count("*"))
        .order_by("_agg_val")[:max_uniques]
    )
    return [{"value": str(row["_agg_val"]), "count": row["_agg_count"]} for row in rows]


# Lazy import to avoid circular — only needed by _uniques
def models_F(field: str) -> Any:  # noqa: N802
    """Return a Django F expression for the given field name."""
    from django.db.models import F

    return F(field)


# ---------------------------------------------------------------------------
# Python-stat computers operating on pre-fetched values lists.
# These mirror ``_py_median`` / ``_py_mode`` / ``_py_stdev`` / ``_py_variance``
# but skip the per-stat DB fetch so a single ``_fetch_values()`` call can be
# reused across every Python stat for the same field.
# ---------------------------------------------------------------------------


def _py_median_from_values(values: list) -> Any:
    """Median of a pre-fetched, unsorted values list (or ``None`` if empty)."""
    if not values:
        return None
    return statistics.median(sorted(values))


def _py_mode_from_values(values: list) -> Any:
    """Mode of a pre-fetched values list (``None`` on empty or StatisticsError)."""
    if not values:
        return None
    try:
        return statistics.mode(values)
    except statistics.StatisticsError:
        return None


def _py_stdev_from_values(values: list) -> float | None:
    """Sample standard deviation, rounded to 2 d.p.  ``None`` if < 2 values."""
    if len(values) <= 1:
        return None
    return round(statistics.stdev([float(v) for v in values]), 2)


def _py_variance_from_values(values: list) -> float | None:
    """Sample variance, rounded to 2 d.p.  ``None`` if < 2 values."""
    if len(values) <= 1:
        return None
    return round(statistics.variance([float(v) for v in values]), 2)


# ---------------------------------------------------------------------------
# Stat registries — classified by execution strategy.
#
# During ``compute()`` the planner walks the requested (field, stat) pairs
# and routes each one to exactly one of these buckets.  The result is a
# single ``.aggregate(**agg_kwargs)`` call for everything in
# ``DB_AGGREGATES`` (+ ``DB_NATIVE_PERCENTILE_STATS`` on PostgreSQL), one
# ``_fetch_values()`` call per field that has any ``PYTHON_STATS``
# requested, and per-stat callables for ``SPECIAL_STATS`` / custom methods.
# ---------------------------------------------------------------------------

# DB aggregate expressions — contributed to one ``.aggregate(**kwargs)`` call.
# Each entry is ``(field_name: str) -> Aggregate``.
DB_AGGREGATES: dict[str, Callable[[str], Aggregate]] = {
    # Count of DISTINCT non-NULL values — ``COUNT(DISTINCT col)`` excludes
    # NULL per SQL standard semantics, matching the previous subquery form
    # ``qs.exclude(field=None).values(field).distinct().count()``.
    "count": lambda f: Count(f, distinct=True),
    "min": lambda f: Min(f),
    "max": lambda f: Max(f),
    "sum": lambda f: Sum(f),
    "mean": lambda f: Avg(f),
    # ``Count("pk", filter=Q(...))`` uses SQL ``FILTER (WHERE …)`` — supported
    # on PostgreSQL and SQLite ≥ 3.30.  Django emulates on older backends.
    "true_count": lambda f: Count("pk", filter=Q(**{f: True})),
    "false_count": lambda f: Count("pk", filter=Q(**{f: False})),
}

# Python stats — operate on a pre-fetched values list.  Fetch once per field,
# reuse across every Python stat requested for that field.
PYTHON_STATS: dict[str, Callable[[list], Any]] = {
    "median": _py_median_from_values,
    "mode": _py_mode_from_values,
    "stdev": _py_stdev_from_values,
    "variance": _py_variance_from_values,
}

# Special — stats that don't fit the plain DB or Python mould.  Currently
# only ``uniques``, which needs its own GROUP BY query to return a list.
SPECIAL_STATS: dict[str, Callable[[QuerySet, str], Any]] = {
    "uniques": _uniques,
}

# PostgreSQL-native expressions for stats that would otherwise require
# fetching the full values list into Python.  When ``settings.IS_POSTGRESQL``
# is true these are folded into the consolidated ``.aggregate()`` call and
# override the Python implementations — removing the
# ``AGGREGATE_MAX_VALUES`` truncation and the separate DB fetch.
#
# Only ``stdev`` and ``variance`` are included here; Django exposes these as
# ``StdDev`` / ``Variance`` on every backend.  ``median`` and ``mode`` stay
# in Python — Django does not ship a cross-backend ``PercentileCont`` or
# ``Mode`` aggregate, and raw-SQL fallbacks aren't worth the complexity for
# this iteration.
DB_NATIVE_PERCENTILE_STATS: dict[str, Callable[[str], Aggregate]] = {
    "stdev": lambda f: StdDev(f, sample=True),
    "variance": lambda f: Variance(f, sample=True),
}


def _alias(counter: int) -> str:
    """Return a unique ``.aggregate()`` kwarg alias.

    The scheme is counter-based rather than a string encoding of the
    ``(field, stat)`` pair — string encoding is not injective once
    either name contains underscores.  For example, with the old
    ``f"_agg_{field}_{stat}"`` form:

    * ``(field="x_true", stat="count")`` → ``_agg_x_true_count``
    * ``(field="x",      stat="true_count")`` → ``_agg_x_true_count``

    …both aliases collide, overwriting one entry in the consolidated
    ``agg_kwargs`` / ``agg_lookup`` and silently returning the wrong
    value for one of the two stats.  A monotonic counter sidesteps the
    encoding problem entirely; the reverse mapping from ``(field, stat)``
    to its alias is recorded in ``agg_lookup`` so assembly stays correct.
    """
    return f"_agg_{counter}"


# ---------------------------------------------------------------------------
# RelatedAggregate
# ---------------------------------------------------------------------------


class RelatedAggregate(LazyRelatedClassMixin):
    """Declares a relationship traversal for nested aggregates.

    Similar to ``RelatedFilter`` / ``RelatedOrder``, this allows an
    ``AdvancedAggregateSet`` to delegate aggregation to a related model's
    aggregate class.

    Usage::

        class ObjectAggregate(AdvancedAggregateSet):
            values = RelatedAggregate(ValueAggregate, field_name="values")

            class Meta:
                model = Object
                fields = {"name": ["count", "min", "max"]}

    This enables queries like::

        allObjects {
          aggregates {
            count
            values {
              count
              value { min max centroid }
            }
          }
        }
    """

    def __init__(self, aggregate_class: str | type, field_name: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._aggregate_class = aggregate_class
        self.field_name = field_name

    def bind_aggregateset(self, aggregateset: type) -> None:
        """Bind the parent aggregateset class for lazy string resolution."""
        if not hasattr(self, "bound_aggregateset"):
            self.bound_aggregateset = aggregateset

    @property
    def aggregate_class(self) -> type:
        """Lazy-load the aggregate class if specified as a string."""
        self._aggregate_class = self.resolve_lazy_class(
            self._aggregate_class,
            getattr(self, "bound_aggregateset", None),
        )
        return self._aggregate_class

    @aggregate_class.setter
    def aggregate_class(self, value: type) -> None:
        self._aggregate_class = value


# ---------------------------------------------------------------------------
# Metaclass
# ---------------------------------------------------------------------------


def _get_field_category(model: type, field_name: str) -> str:
    """Determine the category of a Django model field.

    Args:
        model: The Django model class.
        field_name: The field name on the model.

    Returns:
        One of 'text', 'numeric', 'datetime', 'boolean'.

    Raises:
        ValueError: If the field doesn't exist or has an unrecognised type.
    """
    try:
        field = model._meta.get_field(field_name)
    except Exception as exc:
        raise ValueError(f"Field '{field_name}' does not exist on model '{model.__name__}'.") from exc

    field_class_name = type(field).__name__
    category = FIELD_CATEGORIES.get(field_class_name)
    if category is None:
        raise ValueError(
            f"Field '{field_name}' on model '{model.__name__}' has type "
            f"'{field_class_name}' which is not supported for aggregation. "
            f"Supported types: {sorted(FIELD_CATEGORIES.keys())}"
        )
    return category


class AggregateSetMetaclass(type):
    """Metaclass that validates aggregate configuration at class creation time.

    Inherits ``RelatedAggregate`` declarations from base classes (MRO
    order, later bases win) so that subclassing an ``AdvancedAggregateSet``
    preserves relationship aggregates.  Declarations on the current class
    override same-named declarations on bases — matches standard Python
    attribute lookup.
    """

    def __new__(
        cls: type["AggregateSetMetaclass"],
        name: str,
        bases: tuple,
        attrs: dict[str, Any],
    ) -> "AggregateSetMetaclass":
        """Create and validate a new AggregateSet class."""
        new_class = super().__new__(cls, name, bases, attrs)

        # Collect inherited RelatedAggregates from bases (reversed so
        # later bases override earlier ones — standard MRO semantics),
        # then overlay the current class's own declarations.  This fixes
        # the bug where a subclass silently dropped its parent's
        # ``RelatedAggregate`` attributes because the previous
        # ``attrs.items()``-only pattern never saw inherited fields.
        # (Symmetric to the OrderSetMetaclass fix.)
        related_aggregates: OrderedDict = OrderedDict()
        for base in reversed(bases):
            for n, f in getattr(base, "related_aggregates", {}).items():
                related_aggregates[n] = f
        for n, f in attrs.items():
            if isinstance(f, RelatedAggregate):
                related_aggregates[n] = f

        meta = getattr(new_class, "Meta", None)
        if meta is None or not hasattr(meta, "model") or meta.model is None:
            # Abstract base class or incomplete — skip Meta.fields
            # validation but still publish the inherited related
            # aggregates so downstream subclasses see them.
            new_class._aggregate_config = OrderedDict()
            new_class._custom_stats = {}
            new_class.related_aggregates = related_aggregates
            for f in new_class.related_aggregates.values():
                f.bind_aggregateset(new_class)
            return new_class

        fields = getattr(meta, "fields", {})
        custom_stats = getattr(meta, "custom_stats", {})
        model = meta.model

        config = OrderedDict()
        for field_name, stat_names in fields.items():
            category = _get_field_category(model, field_name)

            valid_for_category = VALID_STATS.get(category, set())
            for stat_name in stat_names:
                # Valid if: built-in for this category, OR custom_stats, OR has compute_ method
                if stat_name not in valid_for_category and stat_name not in custom_stats:
                    compute_method = f"compute_{field_name}_{stat_name}"
                    if compute_method not in attrs:
                        raise ValueError(
                            f"Stat '{stat_name}' is not valid for field '{field_name}' "
                            f"(category='{category}') on '{name}'. "
                            f"Valid built-in stats for '{category}': {sorted(valid_for_category)}. "
                            f"To use a custom stat, add it to Meta.custom_stats or define "
                            f"a '{compute_method}(self, queryset)' method."
                        )

            config[field_name] = {"category": category, "stats": list(stat_names)}

        # "count" is reserved for the root total-row count in the aggregate
        # output type.  A model field named "count" would overwrite it.
        if "count" in config:
            raise ValueError(
                f"Field name 'count' in Meta.fields on '{name}' conflicts with the "
                "reserved root-level aggregate 'count' (total number of records). "
                "Rename the field or exclude it from Meta.fields."
            )

        new_class._aggregate_config = config
        new_class._custom_stats = custom_stats
        new_class.related_aggregates = related_aggregates
        for f in new_class.related_aggregates.values():
            f.bind_aggregateset(new_class)

        # Validate that RelatedAggregate names don't collide with Meta.fields keys.
        overlap = set(config) & set(new_class.related_aggregates)
        if overlap:
            raise ValueError(
                f"Name collision on '{name}': {sorted(overlap)} appear in both "
                "Meta.fields and as RelatedAggregate attributes. "
                "Rename one to avoid ambiguity in the aggregate output type."
            )

        return new_class


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


class AdvancedAggregateSet(ClassBasedTypeNameMixin, metaclass=AggregateSetMetaclass):
    """Declarative aggregate statistics on a filtered queryset.

    Usage::

        class ObjectAggregate(AdvancedAggregateSet):
            class Meta:
                model = Object
                fields = {
                    "name": ["count", "min", "max", "mode", "uniques"],
                    "created_date": ["min", "max"],
                }

    ``ClassBasedTypeNameMixin`` supplies ``type_name_for()`` — returning
    ``{cls.__name__}Type`` for the root and ``{cls.__name__}{Pascal(field)}Type``
    for per-field stat bags.  See ``docs/spec-base_type_naming.md``.
    """

    class Meta:
        """Default Meta — consumers override this."""

        model = None
        fields: dict[str, list[str]] = {}
        custom_stats: dict = {}

    # Suffixes consumed by ``ClassBasedTypeNameMixin.type_name_for``.
    _root_type_suffix = "Type"
    _field_type_suffix = "Type"

    def __init__(self, queryset: QuerySet, request: Any = None) -> None:
        self.queryset = queryset
        self.request = request

    def _related_plan(
        self,
        selection_set: Any,
    ) -> list[tuple[str, RelatedAggregate, Any]]:
        """Return ``(rel_name, rel_agg, child_selection)`` triples to iterate.

        Shared by :meth:`compute` and :meth:`acompute`.  Honours the
        GraphQL selection set so unrequested ``RelatedAggregate`` entries
        are skipped uniformly across both paths; iteration order follows
        ``related_aggregates`` (an ``OrderedDict``) so sync and async
        outputs stay deterministic and byte-identical.
        """
        requested = self._parse_selection_set(selection_set)
        plan: list[tuple[str, RelatedAggregate, Any]] = []
        for rel_name, rel_agg in self.__class__.related_aggregates.items():
            if requested is not None and rel_name not in requested:
                continue
            plan.append((rel_name, rel_agg, self._get_child_selection(selection_set, rel_name)))
        return plan

    def compute(self, selection_set: Any = None, local_only: bool = False) -> dict[str, Any]:
        """Compute aggregate statistics.

        Delegates own-field work to :meth:`_compute_own_fields` (which runs
        the consolidated DB query + per-field value fetches) and then
        recurses into ``RelatedAggregate`` children sequentially.  For an
        async-compatible variant that fans the children out concurrently
        see :meth:`acompute`.

        Args:
            selection_set: Optional GraphQL selection set from ``info``.
                If provided, only stats actually requested are computed.
            local_only: If True, skip ``RelatedAggregate`` traversal.
                Used by nested connection resolvers where nesting is
                handled by the GraphQL query structure itself.

        Returns:
            A dict like ``{"count": 42, "name": {"min": "A", "max": "Z"}, ...}``.
        """
        result = self._compute_own_fields(selection_set)

        if local_only:
            return result

        for rel_name, rel_agg, child_selection in self._related_plan(selection_set):
            # Derive the child queryset by following the relationship.
            # Uses get_child_queryset() which consumers can override for
            # custom visibility scoping (e.g. is_private filtering).
            child_qs = self.get_child_queryset(rel_name, rel_agg)
            child_agg = rel_agg.aggregate_class(queryset=child_qs, request=self.request)
            result[rel_name] = child_agg.compute(selection_set=child_selection)

        return result

    async def acompute(
        self,
        selection_set: Any = None,
        local_only: bool = False,
    ) -> dict[str, Any]:
        """Async variant of :meth:`compute`.

        Own-field aggregation runs via ``sync_to_async(..., thread_sensitive=True)``
        so it shares Django's request-scoped connection / transaction (preserving
        ``ATOMIC_REQUESTS`` semantics).  ``RelatedAggregate`` traversals are
        scheduled concurrently with :func:`asyncio.gather` — the practical win
        here is clean integration with async GraphQL resolvers rather than
        raw parallelism (thread-sensitive mode serialises DB ops on one
        connection; the speedup comes from overlapping any I/O in custom
        ``compute_<field>_<stat>`` methods).

        Output is identical to ``compute(selection_set, local_only)``.
        """
        result = await sync_to_async(self._compute_own_fields, thread_sensitive=True)(selection_set)

        if local_only:
            return result

        plan = self._related_plan(selection_set)
        if not plan:
            return result

        coros = [self._acompute_related(rel_name, rel_agg, sel) for rel_name, rel_agg, sel in plan]
        child_results = await asyncio.gather(*coros)
        for (rel_name, _rel_agg, _sel), child_result in zip(plan, child_results, strict=True):
            result[rel_name] = child_result

        return result

    async def _acompute_related(
        self,
        rel_name: str,
        rel_agg: "RelatedAggregate",
        child_selection: Any,
    ) -> dict[str, Any]:
        """Async helper: derive a child queryset and delegate to ``acompute``."""
        child_qs = await sync_to_async(self.get_child_queryset, thread_sensitive=True)(rel_name, rel_agg)
        child_agg = rel_agg.aggregate_class(queryset=child_qs, request=self.request)
        return await child_agg.acompute(selection_set=child_selection)

    def _compute_own_fields(self, selection_set: Any) -> dict[str, Any]:
        """Compute aggregates for this set's own fields (no related traversal).

        Implements the plan → execute → assemble pipeline documented in
        ``docs/spec-async_and_query_consolidation.md``:

        * **Plan** — classify every requested ``(field, stat)`` into one of
          four buckets (DB aggregate, Python stat, special, custom method),
          record the per-pair routing in ``agg_lookup``.
        * **Execute** — one consolidated ``.aggregate(**agg_kwargs)`` call
          for every DB-level stat; one ``_fetch_values()`` per field that
          has any Python stats; one call each for special + custom stats.
        * **Assemble** — walk the recorded pairs and pull each value from
          the right result bucket.

        Permission checks (``check_<field>_permission`` and
        ``check_<field>_<stat>_permission``) fire in the planning phase
        before any DB work, preserving current cascade order.
        """
        requested = self._parse_selection_set(selection_set)
        result: dict[str, Any] = {"count": self.queryset.count()}

        # ─────────────────────── Phase 1: PLAN ───────────────────────
        agg_kwargs: dict[str, Aggregate] = {}
        agg_lookup: dict[tuple[str, str], str] = {}  # (field, stat) -> alias
        alias_counter = itertools.count()  # monotonic — guarantees unique aliases
        py_plan: dict[str, list[str]] = {}  # field -> [stat, ...]
        special_plan: list[tuple[str, str]] = []
        custom_plan: list[tuple[str, str, Callable]] = []
        requested_fields: list[str] = []
        requested_pairs: list[tuple[str, str]] = []

        for field_name, cfg in self._aggregate_config.items():
            if requested is not None and field_name not in requested:
                continue
            self._check_field_permission(field_name)
            requested_fields.append(field_name)

            for stat_name in cfg["stats"]:
                if requested is not None:
                    fr = requested.get(field_name)
                    if fr is not None and stat_name not in fr:
                        continue
                self._check_stat_permission(field_name, stat_name)
                requested_pairs.append((field_name, stat_name))

                # Resolution order (preserves prior behaviour):
                # 1. compute_<field>_<stat>() override
                # 2. PostgreSQL-native expression (stdev / variance)
                # 3. Generic DB aggregate
                # 4. Python-level stat (needs values fetch)
                # 5. Special-case stat (own query, e.g. uniques)
                method = getattr(self, f"compute_{field_name}_{stat_name}", None)
                if method is not None:
                    custom_plan.append((field_name, stat_name, method))
                elif (  # pragma: no cover — PG-only path
                    settings.IS_POSTGRESQL and stat_name in DB_NATIVE_PERCENTILE_STATS
                ):
                    alias = _alias(next(alias_counter))
                    agg_kwargs[alias] = DB_NATIVE_PERCENTILE_STATS[stat_name](field_name)
                    agg_lookup[(field_name, stat_name)] = alias
                elif stat_name in DB_AGGREGATES:
                    alias = _alias(next(alias_counter))
                    agg_kwargs[alias] = DB_AGGREGATES[stat_name](field_name)
                    agg_lookup[(field_name, stat_name)] = alias
                elif stat_name in PYTHON_STATS:
                    py_plan.setdefault(field_name, []).append(stat_name)
                elif stat_name in SPECIAL_STATS:
                    special_plan.append((field_name, stat_name))

        # ──────────────────── Phase 2: EXECUTE ───────────────────────
        agg_results: dict[str, Any] = self.queryset.aggregate(**agg_kwargs) if agg_kwargs else {}

        py_results: dict[tuple[str, str], Any] = {}
        for field_name, stat_names in py_plan.items():
            # One fetch per field — every Python stat for that field shares it.
            values = _fetch_values(self.queryset, field_name)
            for stat_name in stat_names:
                py_results[(field_name, stat_name)] = PYTHON_STATS[stat_name](values)

        special_results: dict[tuple[str, str], Any] = {
            (f, s): SPECIAL_STATS[s](self.queryset, f) for f, s in special_plan
        }
        custom_results: dict[tuple[str, str], Any] = {(f, s): m(self.queryset) for f, s, m in custom_plan}

        # ──────────────────── Phase 3: ASSEMBLE ──────────────────────
        field_results: dict[str, dict[str, Any]] = {f: {} for f in requested_fields}
        for field_name, stat_name in requested_pairs:
            key = (field_name, stat_name)
            if key in agg_lookup:
                value = agg_results.get(agg_lookup[key])
                # Django's StdDev / Variance return raw floats; the Python
                # path rounds to 2 d.p. — match it for backend parity.
                # Only reachable on PostgreSQL where the PG-native path
                # placed stdev/variance into agg_results.
                if (  # pragma: no cover — PG-only path
                    stat_name in ("stdev", "variance") and value is not None
                ):
                    value = round(value, 2)
                field_results[field_name][stat_name] = value
            elif key in py_results:
                field_results[field_name][stat_name] = py_results[key]
            elif key in special_results:
                field_results[field_name][stat_name] = special_results[key]
            elif key in custom_results:
                field_results[field_name][stat_name] = custom_results[key]

        result.update(field_results)
        return result

    def get_child_queryset(self, rel_name: str, rel_agg: "RelatedAggregate") -> QuerySet:
        """Derive the child queryset for a related aggregate traversal.

        By default, follows the relationship and returns all matching rows.
        Automatically applies ``.distinct()`` when the relationship is
        ManyToMany to prevent inflated counts from join duplicates.

        Override this to apply visibility rules (e.g. ``is_private`` filtering)
        on the child model.

        Args:
            rel_name: The attribute name of the RelatedAggregate on this class.
            rel_agg: The RelatedAggregate instance.

        Returns:
            A queryset of the target model scoped to the parent queryset.

        Note:
            Multi-DB / sharding compatibility: the returned queryset is
            pinned to ``self.queryset.db`` so the ``__in`` subquery stays
            on one database.  See ``docs/spec-db_sharding.md``.
        """
        target_model = rel_agg.aggregate_class.Meta.model
        # Pin to the parent queryset's DB alias so the ``filter(__in=parent_qs)``
        # subquery stays on one database under multi-DB / shard-aware setups.
        qs = target_model._default_manager.using(self.queryset.db).filter(
            **{f"{rel_agg.field_name}__in": self.queryset}
        )

        # Always apply .distinct() — any relationship traversal via
        # filter(field__in=parent_qs) can produce duplicate rows:
        # ManyToMany, ManyToOneRel (reverse FK), and even OneToOne
        # in edge cases with multi-table inheritance.  The cost of
        # .distinct() on an already-unique set is negligible.
        return qs.distinct()

    def _check_field_permission(self, field_name: str) -> None:
        """Call ``check_<field>_permission(request)`` if it exists."""
        method = getattr(self, f"check_{field_name}_permission", None)
        if method:
            method(self.request)

    def _check_stat_permission(self, field_name: str, stat_name: str) -> None:
        """Call ``check_<field>_<stat>_permission(request)`` if it exists."""
        method = getattr(self, f"check_{field_name}_{stat_name}_permission", None)
        if method:
            method(self.request)

    @staticmethod
    def _parse_selection_set(selection_set: Any) -> dict[str, set[str]] | None:
        """Parse a GraphQL selection set into a dict of requested fields and stats.

        Returns ``None`` if no selection set is provided (compute everything).
        Returns a dict like ``{"name": {"min", "max"}, "created_date": {"min"}}``
        if a selection set is present. Related aggregate names are also included
        as keys so they aren't skipped.
        """
        if selection_set is None:
            return None

        requested: dict[str, set[str]] = {}
        for selection in getattr(selection_set, "selections", []):
            field_name = selection.name.value
            if field_name == "count":
                continue
            sub_selections = getattr(selection, "selection_set", None)
            if sub_selections:
                stats = set()
                for sub in sub_selections.selections:
                    stats.add(sub.name.value)
                requested[field_name] = stats
            else:
                requested[field_name] = set()

        # Return the dict even if empty — an empty dict means "selection set
        # was provided but only count was requested, skip all field/related stats".
        # Returning None means "no selection set at all, compute everything".
        return requested

    @staticmethod
    def _get_child_selection(selection_set: Any, field_name: str) -> Any:
        """Extract the sub-selection set for a specific field from a parent selection set."""
        if selection_set is None:
            return None
        for selection in getattr(selection_set, "selections", []):
            if selection.name.value == field_name:
                return getattr(selection, "selection_set", None)
        return None
