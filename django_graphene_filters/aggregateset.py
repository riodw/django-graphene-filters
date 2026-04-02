"""`AdvancedAggregateSet` class module.

Provides a declarative API for computing aggregate statistics on filtered
querysets, analogous to `AdvancedFilterSet` / `AdvancedOrderSet`.
"""

import logging
import statistics
from collections import OrderedDict
from typing import Any

from django.db.models import Avg, Count, Max, Min, QuerySet, Sum

from .aggregate_types import FIELD_CATEGORIES, VALID_STATS
from .conf import settings
from .mixins import LazyRelatedClassMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Python-level helper functions (used by STAT_REGISTRY)
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


def _py_median(qs: QuerySet, field: str) -> Any:
    """Compute median using Python's statistics module."""
    data = sorted(_fetch_values(qs, field))
    return statistics.median(data) if len(data) >= 1 else None


def _py_mode(qs: QuerySet, field: str) -> Any:
    """Compute mode using Python's statistics module."""
    data = _fetch_values(qs, field)
    if not data:
        return None
    try:
        return statistics.mode(data)
    except statistics.StatisticsError:
        return None


def _py_stdev(qs: QuerySet, field: str) -> float | None:
    """Compute standard deviation using Python's statistics module."""
    data = [float(v) for v in _fetch_values(qs, field)]
    return round(statistics.stdev(data), 2) if len(data) > 1 else None


def _py_variance(qs: QuerySet, field: str) -> float | None:
    """Compute variance using Python's statistics module."""
    data = [float(v) for v in _fetch_values(qs, field)]
    return round(statistics.variance(data), 2) if len(data) > 1 else None


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


def _bool_true_count(qs: QuerySet, field: str) -> int:
    """Count rows where the boolean field is True."""
    return qs.filter(**{field: True}).count()


def _bool_false_count(qs: QuerySet, field: str) -> int:
    """Count rows where the boolean field is False."""
    return qs.filter(**{field: False}).count()


# Lazy import to avoid circular — only needed by _uniques
def models_F(field: str) -> Any:  # noqa: N802
    """Return a Django F expression for the given field name."""
    from django.db.models import F

    return F(field)


# ---------------------------------------------------------------------------
# Built-in stat registry
# ---------------------------------------------------------------------------

STAT_REGISTRY: dict[str, Any] = {
    # DB-level (single aggregate query, efficient)
    "count": lambda qs, field: qs.exclude(**{field: None}).values(field).distinct().count(),
    "min": lambda qs, field: qs.aggregate(v=Min(field))["v"],
    "max": lambda qs, field: qs.aggregate(v=Max(field))["v"],
    "sum": lambda qs, field: qs.aggregate(v=Sum(field))["v"],
    "mean": lambda qs, field: qs.aggregate(v=Avg(field))["v"],
    # Python-level (fetches values into memory)
    "median": _py_median,
    "mode": _py_mode,
    "stdev": _py_stdev,
    "variance": _py_variance,
    # Grouped query
    "uniques": _uniques,
    # Boolean-specific
    "true_count": _bool_true_count,
    "false_count": _bool_false_count,
}


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
    """Metaclass that validates aggregate configuration at class creation time."""

    def __new__(
        cls: type["AggregateSetMetaclass"],
        name: str,
        bases: tuple,
        attrs: dict[str, Any],
    ) -> "AggregateSetMetaclass":
        """Create and validate a new AggregateSet class."""
        new_class = super().__new__(cls, name, bases, attrs)

        meta = getattr(new_class, "Meta", None)
        if meta is None or not hasattr(meta, "model") or meta.model is None:
            # Abstract base class or incomplete — skip validation
            new_class._aggregate_config = OrderedDict()
            new_class._custom_stats = {}
            new_class.related_aggregates = OrderedDict()
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

        # Discover RelatedAggregate declarations on the class
        new_class.related_aggregates = OrderedDict(
            [(n, f) for n, f in attrs.items() if isinstance(f, RelatedAggregate)]
        )
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


class AdvancedAggregateSet(metaclass=AggregateSetMetaclass):
    """Declarative aggregate statistics on a filtered queryset.

    Usage::

        class ObjectAggregate(AdvancedAggregateSet):
            class Meta:
                model = Object
                fields = {
                    "name": ["count", "min", "max", "mode", "uniques"],
                    "created_date": ["min", "max"],
                }
    """

    class Meta:
        """Default Meta — consumers override this."""

        model = None
        fields: dict[str, list[str]] = {}
        custom_stats: dict = {}

    def __init__(self, queryset: QuerySet, request: Any = None) -> None:
        self.queryset = queryset
        self.request = request

    def compute(self, selection_set: Any = None, local_only: bool = False) -> dict[str, Any]:
        """Compute aggregate statistics.

        Args:
            selection_set: Optional GraphQL selection set from ``info``.
                If provided, only stats actually requested are computed.
            local_only: If True, skip ``RelatedAggregate`` traversal.
                Used by nested connection resolvers where nesting is
                handled by the GraphQL query structure itself.

        Returns:
            A dict like ``{"count": 42, "name": {"min": "A", "max": "Z"}, ...}``.
        """
        result: dict[str, Any] = {"count": self.queryset.count()}
        requested = self._parse_selection_set(selection_set)

        # Compute stats on own fields
        for field_name, config in self._aggregate_config.items():
            # Skip fields not requested
            if requested is not None and field_name not in requested:
                continue

            # Field-level permission check
            self._check_field_permission(field_name)

            field_result: dict[str, Any] = {}
            for stat_name in config["stats"]:
                # Skip stats not requested
                if requested is not None:
                    field_requested = requested.get(field_name)
                    if field_requested is not None and stat_name not in field_requested:
                        continue

                # Stat-level permission check
                self._check_stat_permission(field_name, stat_name)

                # Resolution order:
                # 1. compute_<field>_<stat>() override on the class
                # 2. STAT_REGISTRY built-in
                method = getattr(self, f"compute_{field_name}_{stat_name}", None)
                if method:
                    field_result[stat_name] = method(self.queryset)
                elif stat_name in STAT_REGISTRY:
                    field_result[stat_name] = STAT_REGISTRY[stat_name](self.queryset, field_name)

            result[field_name] = field_result

        # Compute related aggregates (relationship traversal)
        if local_only:
            return result
        for rel_name, rel_agg in self.__class__.related_aggregates.items():
            if requested is not None and rel_name not in requested:
                continue

            # Derive the child queryset by following the relationship.
            # Uses get_child_queryset() which consumers can override for
            # custom visibility scoping (e.g. is_private filtering).
            child_qs = self.get_child_queryset(rel_name, rel_agg)

            # Extract the sub-selection set for this related aggregate
            child_selection = self._get_child_selection(selection_set, rel_name)

            # Delegate to the child aggregate class
            child_agg = rel_agg.aggregate_class(queryset=child_qs, request=self.request)
            result[rel_name] = child_agg.compute(selection_set=child_selection)

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
        """
        target_model = rel_agg.aggregate_class.Meta.model
        qs = target_model._default_manager.filter(**{f"{rel_agg.field_name}__in": self.queryset})

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
