"""Module for converting an AdvancedOrderSet class to ordering arguments.

Class-based naming (see ``docs/spec-base_type_naming.md``): every
``AdvancedOrderSet`` maps to one stable GraphQL input type derived from the
class name alone.  ``RelatedOrder`` traversals emit a lambda reference to
the target orderset's root type rather than an inline subtree — the same
pattern used by ``FilterArgumentsFactory`` — so a given OrderSet always
resolves to the same root type regardless of which connection reached it.
"""

import warnings
from typing import cast

import graphene

from .mixins import InputObjectTypeFactoryMixin


class OrderDirection(graphene.Enum):
    """Enum to represent the sorting direction of a field.

    ``ASC_DISTINCT`` and ``DESC_DISTINCT`` combine ordering with
    ``DISTINCT ON`` partitioning.  Fields marked with a ``*_DISTINCT``
    direction define the partition key; subsequent ``orderBy`` entries
    act as tie-breakers within each partition (determining which row
    survives per group).
    """

    ASC = "asc"
    DESC = "desc"
    ASC_DISTINCT = "asc_distinct"
    DESC_DISTINCT = "desc_distinct"


class OrderArgumentsFactory(InputObjectTypeFactoryMixin):
    """Factory for creating ordering arguments in GraphQL from an AdvancedOrderSet class."""

    # Tracks which orderset class built each cached type name.  Under class-based
    # naming a collision means two distinct classes share a ``__name__`` — always
    # a bug (either two modules declared the same class or schema build ran twice
    # with stale caches).  Strict raise, not warn.
    _type_orderset_registry: dict[str, type] = {}

    def __init__(
        self,
        orderset_class: type,
        input_type_prefix: str | None = None,
    ) -> None:
        """Initialize the factory.

        Args:
            orderset_class: The ``AdvancedOrderSet`` class to convert.
            input_type_prefix: **Deprecated.** Ignored under class-based
                naming — the type name is derived from
                ``orderset_class.type_name_for()``.  Emits a
                :class:`DeprecationWarning` if non-``None``. Removed in 1.1.
        """
        if input_type_prefix is not None:
            warnings.warn(
                "OrderArgumentsFactory `input_type_prefix` is ignored under class-based "
                "naming and will be removed in 1.1. The generated type name is now derived "
                "from `orderset_class.type_name_for()`.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.orderset_class = orderset_class
        self.order_input_type_name = orderset_class.type_name_for()

    @property
    def arguments(self) -> dict[str, graphene.Argument]:
        """Create and return the GraphQL arguments for ordering.

        BFS-builds ``self.orderset_class`` and every ``RelatedOrder`` descendant
        so that all lambda references resolve by schema-finalize time.  Idempotent:
        subsequent calls for the same OrderSet hit the cache.
        """
        self._ensure_built()
        self._check_collision(self.order_input_type_name, self.orderset_class)
        input_object_type = self.input_object_types[self.order_input_type_name]
        return {
            "orderBy": graphene.Argument(
                graphene.List(graphene.NonNull(input_object_type)),
                description="Advanced ordering field (array of objects for priority matching)",
            ),
        }

    def _ensure_built(self) -> None:
        """BFS-build ``self.orderset_class`` and all related-order descendants.

        Cycles (A → B → A) are handled naturally: an orderset already in
        ``seen`` is skipped, and lambda refs resolve once the BFS finishes.
        """
        pending: list[type] = [self.orderset_class]
        seen: set[type] = set()
        while pending:
            os_class = pending.pop()
            if os_class in seen:
                continue
            seen.add(os_class)

            target_name = os_class.type_name_for()
            if target_name not in self.input_object_types:
                self._build_class_type(os_class)
            else:
                self._check_collision(target_name, os_class)

            # Enqueue every RelatedOrder target reachable from this orderset.
            for rel_order in getattr(os_class, "related_orders", {}).values():
                target = rel_order.orderset
                if target is not None and target not in seen:
                    pending.append(target)

    def _check_collision(self, type_name: str, os_class: type) -> None:
        """Raise if ``type_name`` is already registered for a different class."""
        prior = self._type_orderset_registry.get(type_name)
        if prior is not None and prior is not os_class:
            raise TypeError(
                f"Class-based naming collision: GraphQL type '{type_name}' is already "
                f"registered by '{prior.__module__}.{prior.__qualname__}' but now "
                f"'{os_class.__module__}.{os_class.__qualname__}' is trying to claim "
                "the same name. Rename one of the orderset classes."
            )

    def _build_class_type(self, os_class: type) -> None:
        """Build the root ``InputObjectType`` for ``os_class`` and cache it.

        Leaf fields get an ``OrderDirection`` input field; ``RelatedOrder`` fields
        emit a lambda reference to the target orderset's root type (mirrors the
        ``and`` / ``or`` / ``not`` self-ref pattern in ``FilterArgumentsFactory``).
        """
        type_name = os_class.type_name_for()
        fields: dict[str, graphene.InputField] = {}

        for field_name, related_order in os_class.get_fields().items():
            if related_order is not None:
                target_os = related_order.orderset
                if target_os is not None:
                    target_name = target_os.type_name_for()
                    fields[field_name] = graphene.InputField(
                        lambda tn=target_name: self.input_object_types[tn],
                    )
            else:
                # Flat field (no traversal, leaf node)
                fields[field_name] = graphene.InputField(OrderDirection)

        self.input_object_types[type_name] = cast(
            type[graphene.InputObjectType],
            type(
                type_name,
                (graphene.InputObjectType,),
                fields,
            ),
        )
        self._type_orderset_registry[type_name] = os_class
