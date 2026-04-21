"""`AdvancedOrderSet` class module."""

import enum
from collections import OrderedDict
from collections.abc import Mapping
from typing import Any

from graphene.utils.str_converters import to_snake_case

from . import orders
from .mixins import get_concrete_field_names


class OrderSetMetaclass(type):
    """Custom metaclass for creating OrderSet classes and attaching RelatedOrders."""

    def __new__(cls, name: str, bases: tuple, attrs: dict[str, Any]) -> "OrderSetMetaclass":
        """Create a new OrderSet class and populate ``related_orders``.

        Inherits ``RelatedOrder`` declarations from base classes so that
        subclassing an ``AdvancedOrderSet`` preserves relationship ordering
        support.  Declarations on the current class override same-named
        declarations on bases (standard Python MRO semantics).
        """
        new_class = super().__new__(cls, name, bases, attrs)

        # Start with inherited related_orders from base classes (in MRO order,
        # with later bases overriding earlier ones — matches Python's method
        # resolution).
        inherited: OrderedDict = OrderedDict()
        for base in reversed(bases):
            for n, f in getattr(base, "related_orders", {}).items():
                inherited[n] = f

        # Apply the current class's own declarations, overriding inherited ones.
        for n, f in attrs.items():
            if isinstance(f, orders.BaseRelatedOrder):
                inherited[n] = f

        new_class.related_orders = inherited
        for f in new_class.related_orders.values():
            f.bind_orderset(new_class)
        return new_class


class AdvancedOrderSet(metaclass=OrderSetMetaclass):
    """Base class for advanced relationship sorting with permission checks."""

    @classmethod
    def type_name_for(cls) -> str:
        """Return the GraphQL input type name for this orderset.

        Class-based naming: every orderset maps to one stable type name
        derived from ``cls.__name__`` — no node prefix, no traversal-path
        accumulation. See ``docs/spec-base_type_naming.md``.
        """
        return f"{cls.__name__}InputType"

    def __init__(
        self,
        data: list | None = None,
        queryset: Any = None,
        request: Any = None,
    ) -> None:
        self.data = data or []
        self.qs = queryset
        self.request = request
        self._distinct_fields: list[str] = []

        if self.data and self.qs is not None:
            # Flatten the GraphQL nested InputObjectType array into Django __ paths.
            # Also collects fields marked with *_DISTINCT directions.
            flat_orders, self._distinct_fields = self.get_flat_orders(self.data)

            # Hook validation (so you can reject before applying)
            self.check_permissions(self.request, flat_orders)

            # Apply ordering to QuerySet
            self.qs = self.qs.order_by(*flat_orders)

            # Apply distinct-on AFTER ordering (order determines which row is kept per group)
            if self._distinct_fields:
                self.qs = self.apply_distinct(self.qs, self._distinct_fields, flat_orders)

    def check_permissions(self, request: Any, requested_orderings: list[str]) -> None:
        """Validate whether the user is allowed to order by these fields.

        It looks for strictly matching methods on the orderset prefixed by `check_` and `_permission`.
        E.g. for `category__name`, it searches for `check_category_name_permission(request)`.
        If the user lacks permission, you can raise an error or drop the field.

        For related paths (e.g. `object_type__name`), the check is also delegated
        to the child orderset so that permission methods defined there are honoured.
        """
        for order_path in requested_orderings:
            # Remove leading `-`
            clean_path = order_path.lstrip("-")
            method_name = f"check_{clean_path.replace('__', '_')}_permission"

            if hasattr(self, method_name):
                getattr(self, method_name)(request)

            # Delegate to the child orderset that owns the remainder of the path
            for rel_order in getattr(self.__class__, "related_orders", {}).values():
                prefix = f"{rel_order.field_name}__"
                if clean_path.startswith(prefix):
                    remainder = clean_path[len(prefix) :]
                    target_class = rel_order.orderset
                    if target_class:
                        child = object.__new__(target_class)
                        child.check_permissions(request, [remainder])
                    break

    @classmethod
    def get_flat_orders(cls, order_data: list, prefix: str = "") -> tuple[list[str], list[str]]:
        """Recursively parse nested order dicts into flat ORM paths.

        Returns:
            A ``(flat_orders, distinct_fields)`` tuple.

            * **flat_orders** — ORM order strings, e.g. ``["-name", "object_type__name"]``
            * **distinct_fields** — bare field paths (no ``-`` prefix) for fields
              whose direction was ``ASC_DISTINCT`` or ``DESC_DISTINCT``
        """
        flat_orders: list[str] = []
        distinct_fields: list[str] = []

        for order_item in order_data:
            if isinstance(order_item, Mapping):
                # An item generally possesses exactly one key -> value representing one hop
                for key, value in order_item.items():
                    snake_key = to_snake_case(key)
                    related_orders = getattr(cls, "related_orders", {})

                    if snake_key in related_orders:
                        # Fetch correct model field_name in case it diverges from GraphQL alias
                        real_field_name = related_orders[snake_key].field_name
                        current_prefix = f"{prefix}{real_field_name}__"

                        target_orderset = related_orders[snake_key].orderset
                        if isinstance(value, Mapping) and target_orderset:
                            # Recurse with prefix (e.g., 'category__')
                            sub_orders, sub_distinct = target_orderset.get_flat_orders(
                                [value], current_prefix
                            )
                            flat_orders.extend(sub_orders)
                            distinct_fields.extend(sub_distinct)
                    else:
                        current_prefix = f"{prefix}{snake_key}__"

                        if isinstance(value, Mapping):
                            # Native field recurse if any
                            sub_orders, sub_distinct = cls.get_flat_orders([value], current_prefix)
                            flat_orders.extend(sub_orders)
                            distinct_fields.extend(sub_distinct)
                        else:
                            # Reached the leaf node -> direction is attached here
                            direction_str = value.value if isinstance(value, enum.Enum) else str(value)
                            is_distinct = direction_str.endswith("_distinct")
                            clean_direction = direction_str.replace("_distinct", "")

                            direction = "-" if clean_direction.lower() == "desc" else ""
                            field_path = current_prefix.removesuffix("__")
                            flat_orders.append(f"{direction}{field_path}")

                            if is_distinct:
                                distinct_fields.append(field_path)

        return flat_orders, distinct_fields

    @classmethod
    def apply_distinct(
        cls,
        queryset: Any,
        distinct_fields: list[str],
        order_fields: list[str],
    ) -> Any:
        """Apply ``DISTINCT ON`` to the queryset.

        PostgreSQL uses native ``.distinct(*fields)`` — but only when the
        queryset does not have a ``GROUP BY`` clause.  Django raises
        ``NotImplementedError("annotate() + distinct(fields) is not
        implemented.")`` when ``.distinct(*fields)`` is combined with an
        aggregate-bearing queryset.  In that case (and for all non-PostgreSQL
        backends) we fall back to ``Window(RowNumber())`` emulation.
        """
        from .conf import settings

        has_group_by = bool(getattr(queryset.query, "group_by", None))

        if settings.IS_POSTGRESQL and not has_group_by:
            return cls._apply_distinct_postgres(queryset, distinct_fields, order_fields)
        return cls._apply_distinct_emulated(queryset, distinct_fields, order_fields)

    @staticmethod
    def _apply_distinct_postgres(queryset: Any, distinct_fields: list[str], order_fields: list[str]) -> Any:
        """Native PostgreSQL ``DISTINCT ON``.

        PostgreSQL requires ``DISTINCT ON`` fields to be the leftmost
        columns in ``ORDER BY``.  We deduplicate to avoid invalid SQL
        like ``ORDER BY name DESC, name ASC`` when the same field appears
        in both distinct and regular ordering.
        """
        distinct_set = set(distinct_fields)
        # Remove order_fields that duplicate a distinct field
        deduped_order = [f for f in order_fields if f.lstrip("-") not in distinct_set]

        # Extract the distinct fields' order entries (with their direction),
        # keeping only the FIRST occurrence per stripped path so that
        # [{name: DESC_DISTINCT}, {name: ASC}] doesn't produce
        # ORDER BY name DESC, name ASC.
        distinct_order: list[str] = []
        seen: set[str] = set()
        for f in order_fields:
            stripped = f.lstrip("-")
            if stripped in distinct_set and stripped not in seen:
                distinct_order.append(f)
                seen.add(stripped)
        # If a distinct field wasn't in order_fields at all, add it bare
        for field in distinct_fields:
            if field not in seen:
                distinct_order.append(field)
                seen.add(field)

        full_order = distinct_order + deduped_order
        if full_order:
            queryset = queryset.order_by(*full_order)
        return queryset.distinct(*distinct_fields)

    @staticmethod
    def _apply_distinct_emulated(queryset: Any, distinct_fields: list[str], order_fields: list[str]) -> Any:
        """Emulated ``DISTINCT ON`` using Window functions.

        Works on all Django-supported backends (SQLite, MySQL 8+,
        Oracle, MariaDB 10.2+) — all set ``supports_over_clause = True``
        as of Django 4.2+.

        Django automatically wraps the window-annotated queryset in a
        subquery when ``.filter()`` is applied to a window column.
        """
        from django.db.models import F, Window
        from django.db.models.functions import RowNumber

        partition_by = [F(field) for field in distinct_fields]

        if order_fields:
            window_order = []
            for field in order_fields:
                if field.startswith("-"):
                    window_order.append(F(field[1:]).desc())
                else:
                    window_order.append(F(field).asc())
        else:
            window_order = [F("pk").asc()]

        return queryset.annotate(
            _distinct_row_num=Window(
                expression=RowNumber(),
                partition_by=partition_by,
                order_by=window_order,
            )
        ).filter(_distinct_row_num=1)

    @classmethod
    def get_fields(cls) -> OrderedDict:
        """Fetches flat order fields from the Meta definitions merging with explicit Relationships."""
        fields = OrderedDict()
        if hasattr(cls, "Meta") and hasattr(cls.Meta, "fields"):
            meta_fields = cls.Meta.fields
            if meta_fields == "__all__":
                # Resolve all concrete model fields (excluding relations)
                model = getattr(cls.Meta, "model", None)
                if model:
                    for name in get_concrete_field_names(model):
                        fields[name] = None
            else:
                # Works for both dict (iterates keys) and list/tuple (iterates values)
                for k in meta_fields:
                    fields[k] = None

        for k, v in getattr(cls, "related_orders", {}).items():
            fields[k] = v

        return fields
