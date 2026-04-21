"""Module for converting an AdvancedAggregateSet class to aggregate output types.

Class-based naming (see ``docs/spec-base_type_naming.md``): every
``AdvancedAggregateSet`` maps to one stable GraphQL output type derived from
the class name alone.  ``RelatedAggregate`` traversals emit a lambda
reference to the target aggregateset's root type rather than an inline
subtree — mirroring the ``FilterArgumentsFactory`` / ``OrderArgumentsFactory``
pattern — so a given AggregateSet always resolves to the same root type
regardless of which connection reached it.
"""

from typing import cast

import graphene

from .aggregate_types import STAT_TYPES
from .aggregateset import AdvancedAggregateSet
from .mixins import ObjectTypeFactoryMixin
from .utils import raise_on_type_name_collision


class AggregateArgumentsFactory(ObjectTypeFactoryMixin):
    """Factory for creating aggregate output types in GraphQL from an AdvancedAggregateSet class.

    Analogous to ``FilterArgumentsFactory`` / ``OrderArgumentsFactory``, but generates
    output ``ObjectType`` classes (not ``InputObjectType``) since aggregates are returned
    in the response, not passed as arguments.
    """

    # Tracks which aggregateset class built each cached type name.  Under class-based
    # naming a collision means two distinct classes share a ``__name__`` — always
    # a bug (either two modules declared the same class or schema build ran twice
    # with stale caches).  Strict raise, not warn.
    _type_aggregate_registry: dict[str, type] = {}

    def __init__(self, aggregate_class: type[AdvancedAggregateSet]) -> None:
        """Initialize the factory.

        Args:
            aggregate_class: The ``AdvancedAggregateSet`` class to convert.
                The generated GraphQL type name derives from
                ``aggregate_class.type_name_for()``.
        """
        self.aggregate_class = aggregate_class
        self.aggregate_type_name = aggregate_class.type_name_for()

    def build_aggregate_type(self) -> type[graphene.ObjectType]:
        """Build and return the root aggregate ObjectType.

        BFS-builds ``self.aggregate_class`` and every ``RelatedAggregate`` descendant
        so that all lambda references resolve by schema-finalize time.  Idempotent:
        subsequent calls for the same AggregateSet hit the cache.

        For an ObjectAggregate with fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
            "created_date": ["min", "max"],
        }

        Generates::

            class ObjectAggregateType(ObjectType):
                count = Int()
                name = Field(ObjectAggregateNameType)
                created_date = Field(ObjectAggregateCreatedDateType)

            class ObjectAggregateNameType(ObjectType):
                count = Int()
                min = String()
                max = String()
                mode = String()
                uniques = List(UniqueValueType)

            class ObjectAggregateCreatedDateType(ObjectType):
                min = DateTime()
                max = DateTime()

        Returns:
            The root aggregate ObjectType class.
        """
        self._ensure_built()
        raise_on_type_name_collision(
            self.aggregate_type_name,
            self.aggregate_class,
            self._type_aggregate_registry,
            "aggregateset",
        )
        return self.object_types[self.aggregate_type_name]

    def _ensure_built(self) -> None:
        """BFS-build ``self.aggregate_class`` and all related-aggregate descendants.

        Cycles (A → B → A) are handled naturally: the enqueue-time
        ``target not in seen`` gate stops cycles from looping.  Lambda refs
        resolve once the BFS finishes.
        """
        pending: list[type[AdvancedAggregateSet]] = [self.aggregate_class]
        seen: set[type[AdvancedAggregateSet]] = set()
        while pending:
            ag_class = pending.pop()
            seen.add(ag_class)

            target_name = ag_class.type_name_for()
            if target_name not in self.object_types:
                self._build_class_type(ag_class)
            else:
                raise_on_type_name_collision(
                    target_name,
                    ag_class,
                    self._type_aggregate_registry,
                    "aggregateset",
                )

            # Enqueue every RelatedAggregate target reachable from this aggregateset.
            # ``None`` targets are skipped — users may declare
            # ``RelatedAggregate(None, ...)`` as a placeholder that drops out of
            # the emitted schema rather than raising.
            for rel_agg in getattr(ag_class, "related_aggregates", {}).values():
                target = rel_agg.aggregate_class
                if target is not None and target not in seen:
                    pending.append(target)

    def _build_class_type(self, ag_class: type[AdvancedAggregateSet]) -> None:
        """Build the root ``ObjectType`` for ``ag_class`` and cache it.

        Per-field stat bags use ``ag_class.type_name_for(field_name)``.
        ``RelatedAggregate`` fields emit a lambda reference to the target
        aggregateset's root type — parallel to the filter/order lazy refs.
        """
        config = ag_class._aggregate_config
        custom_stats = ag_class._custom_stats

        # Root-level count is always present
        root_fields: dict[str, graphene.Field | graphene.Scalar] = {
            "count": graphene.Int(description="Total number of records in the filtered result set"),
        }

        for field_name, field_config in config.items():
            category = field_config["category"]
            stat_names = field_config["stats"]

            # Build per-field sub-type
            sub_fields = self._build_stat_fields(category, stat_names, custom_stats)
            sub_type_name = ag_class.type_name_for(field_name)
            sub_type = self.create_object_type(sub_type_name, sub_fields)

            root_fields[field_name] = graphene.Field(
                sub_type,
                description=f"Aggregate statistics for `{field_name}`",
            )

        # RelatedAggregate children → lambda ref to the target's root type.
        # The BFS in ``_ensure_built`` guarantees the target type is in
        # ``self.object_types`` by the time graphene resolves the lambda.
        # ``None`` targets (from ``RelatedAggregate(None, ...)`` placeholders)
        # are skipped so the field simply isn't emitted.
        for rel_name, rel_agg in getattr(ag_class, "related_aggregates", {}).items():
            target_class = rel_agg.aggregate_class
            if target_class is None:
                continue
            target_name = target_class.type_name_for()
            root_fields[rel_name] = graphene.Field(
                lambda tn=target_name: self.object_types[tn],
                description=f"Aggregates across `{rel_name}` relationship",
            )

        root_type_name = ag_class.type_name_for()
        self.object_types[root_type_name] = cast(
            type[graphene.ObjectType],
            type(
                root_type_name,
                (graphene.ObjectType,),
                root_fields,
            ),
        )
        self._type_aggregate_registry[root_type_name] = ag_class

    @staticmethod
    def _build_stat_fields(
        category: str,
        stat_names: list[str],
        custom_stats: dict,
    ) -> dict[str, graphene.Scalar | graphene.List]:
        """Build the graphene fields for a set of stat names.

        Args:
            category: The field category ('text', 'numeric', 'datetime', 'boolean').
            stat_names: List of stat names to include.
            custom_stats: Custom stat name -> graphene type mapping.

        Returns:
            A dict of {stat_name: graphene_field_instance}.
        """
        fields: dict = {}
        category_types = STAT_TYPES.get(category, {})

        for stat_name in stat_names:
            if stat_name in custom_stats:
                # Custom stat — type provided by the consumer
                gql_type = custom_stats[stat_name]
                fields[stat_name] = gql_type(description=f"Custom stat: `{stat_name}`")
            elif stat_name in category_types:
                # Built-in stat — type from STAT_TYPES registry
                gql_type = category_types[stat_name]
                if isinstance(gql_type, graphene.List):
                    # Already instantiated (e.g. List(UniqueValueType))
                    fields[stat_name] = graphene.Field(
                        gql_type,
                        description=f"`{stat_name}` stat",
                    )
                else:
                    fields[stat_name] = gql_type(description=f"`{stat_name}` stat")

        return fields
