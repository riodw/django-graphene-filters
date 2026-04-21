"""Module for converting a AdvancedFilterSet class to filter arguments.

Class-based naming (see ``docs/spec-base_type_naming.md``): every
``AdvancedFilterSet`` maps to one stable GraphQL input type derived from the
class name alone.  ``RelatedFilter`` traversals emit a lambda reference to
the target filterset's root type rather than an inline subtree — so the same
``BrandFilter`` always resolves to the same ``BrandFilterInputType``, whatever
connection reached it.  Apollo and any name-keyed schema cache dedupe the
shared types across pages.
"""

import warnings
from collections.abc import Callable, Sequence
from typing import cast

import graphene
from anytree import Node
from django.db.models.constants import LOOKUP_SEP
from django_filters import Filter
from django_filters.conf import settings as django_settings
from graphene_django.filter.utils import get_model_field
from graphene_django.forms.converter import convert_form_field
from stringcase import pascalcase

from .conf import settings
from .filters import BaseRelatedFilter, SearchQueryFilter, SearchRankFilter, TrigramFilter
from .filterset import AdvancedFilterSet
from .input_types import (
    SearchQueryFilterInputType,
    SearchRankFilterInputType,
    TrigramFilterInputType,
)
from .mixins import InputObjectTypeFactoryMixin


class FilterArgumentsFactory(InputObjectTypeFactoryMixin):
    """Factory for creating filter arguments in GraphQL from a given `AdvancedFilterSet` class."""

    # Special GraphQL filter input types and their associated factories
    SPECIAL_FILTER_INPUT_TYPES_FACTORIES: dict[str, Callable[[], graphene.InputField]] = {
        SearchQueryFilter.postfix: lambda: graphene.InputField(
            SearchQueryFilterInputType,
            description="Field for the full-text search using `SearchVector` and `SearchQuery` objects.",
        ),
        SearchRankFilter.postfix: lambda: graphene.InputField(
            SearchRankFilterInputType,
            description="Field for the full-text search using the `SearchRank` object.",
        ),
        TrigramFilter.postfix: lambda: graphene.InputField(
            TrigramFilterInputType,
            description="Field for the full-text search using trigram similarity or trigram distance.",
        ),
    }

    # Cache for storing input object types, keyed by class-derived name.
    input_object_types: dict[str, type[graphene.InputObjectType]] = {}

    # Tracks which filterset class built each cached type name.  Under class-based
    # naming a collision means two distinct classes share a ``__name__`` — that's
    # always a bug (either two modules declared the same class or schema build
    # ran twice with stale caches).  Strict raise, not warn.
    _type_filterset_registry: dict[str, type] = {}

    def __init__(
        self,
        filterset_class: type[AdvancedFilterSet],
        input_type_prefix: str | None = None,
    ) -> None:
        """Initialize the factory.

        Args:
            filterset_class: The ``AdvancedFilterSet`` class to convert.
            input_type_prefix: **Deprecated.** Ignored under class-based
                naming — the type name is derived from
                ``filterset_class.type_name_for()``.  Emits a
                :class:`DeprecationWarning` if non-``None``. Removed in 1.1.
        """
        if input_type_prefix is not None:
            warnings.warn(
                "FilterArgumentsFactory `input_type_prefix` is ignored under class-based "
                "naming and will be removed in 1.1. The generated type name is now derived "
                "from `filterset_class.type_name_for()`.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.filterset_class = filterset_class
        self.filter_input_type_name = filterset_class.type_name_for()

    @property
    def arguments(self) -> dict[str, graphene.Argument]:
        """Create and return the GraphQL arguments for filtering.

        BFS-builds ``self.filterset_class`` and every ``RelatedFilter`` descendant
        so that all lambda references resolve by schema-finalize time.  Idempotent:
        subsequent calls for the same FilterSet hit the cache.
        """
        self._ensure_built()
        self._check_collision(self.filter_input_type_name, self.filterset_class)
        input_object_type = self.input_object_types[self.filter_input_type_name]
        return {
            settings.FILTER_KEY: graphene.Argument(
                input_object_type,
                description="Advanced filter field",
            ),
        }

    def _ensure_built(self) -> None:
        """BFS-build ``self.filterset_class`` and all related-filter descendants.

        Cycles (A → B → A) are handled naturally: a filterset already in
        ``seen`` is skipped, and lambda refs resolve once the BFS finishes.
        """
        pending: list[type[AdvancedFilterSet]] = [self.filterset_class]
        seen: set[type[AdvancedFilterSet]] = set()
        while pending:
            fs_class = pending.pop()
            if fs_class in seen:
                continue
            seen.add(fs_class)

            target_name = fs_class.type_name_for()
            if target_name not in self.input_object_types:
                # Build this filterset's root type.
                self._build_class_type(fs_class)
            else:
                self._check_collision(target_name, fs_class)

            # Enqueue every RelatedFilter target reachable from this filterset.
            for rel_filter in getattr(fs_class, "related_filters", {}).values():
                target = rel_filter.filterset
                if target is not None and target not in seen:
                    pending.append(target)

    def _check_collision(self, type_name: str, fs_class: type[AdvancedFilterSet]) -> None:
        """Raise if ``type_name`` is already registered for a different class."""
        prior = self._type_filterset_registry.get(type_name)
        if prior is not None and prior is not fs_class:
            raise TypeError(
                f"Class-based naming collision: GraphQL type '{type_name}' is already "
                f"registered by '{prior.__module__}.{prior.__qualname__}' but now "
                f"'{fs_class.__module__}.{fs_class.__qualname__}' is trying to claim "
                "the same name. Rename one of the filterset classes."
            )

    def _build_class_type(self, fs_class: type[AdvancedFilterSet]) -> None:
        """Build the root ``InputObjectType`` for ``fs_class`` and cache it."""
        type_name = fs_class.type_name_for()
        input_fields = self._build_input_fields(fs_class)
        logic_fields = self._build_logic_fields(type_name)

        self.input_object_types[type_name] = cast(
            type[graphene.InputObjectType],
            type(
                type_name,
                (graphene.InputObjectType,),
                {**input_fields, **logic_fields},
            ),
        )
        self._type_filterset_registry[type_name] = fs_class

    def _build_logic_fields(self, type_name: str) -> dict[str, graphene.InputField]:
        """``and`` / ``or`` / ``not`` logical combinators — all self-referential."""
        return {
            settings.AND_KEY: graphene.InputField(
                graphene.List(lambda: self.input_object_types[type_name]),
                description="`And` field",
            ),
            settings.OR_KEY: graphene.InputField(
                graphene.List(lambda: self.input_object_types[type_name]),
                description="`Or` field",
            ),
            settings.NOT_KEY: graphene.InputField(
                lambda: self.input_object_types[type_name],
                description="`Not` field",
            ),
        }

    def _build_input_fields(
        self,
        fs_class: type[AdvancedFilterSet],
    ) -> dict[str, graphene.InputField]:
        """Build the top-level input fields for a filterset's root type.

        Iterates the trees produced by :meth:`filterset_to_trees` and dispatches:

        * **Full-text search postfix** (``full_text_search`` / ``search_query`` /
          ``trigram``) → routed through ``SPECIAL_FILTER_INPUT_TYPES_FACTORIES``.
        * **RelatedFilter boundary with no direct lookups** (name matches a key
          in ``cls.related_filters`` and its subtree contains only nested chains)
          → lambda reference to the target filterset's root type.  The subtree
          under this root is intentionally *not* rendered — the target's own
          schema owns those fields.
        * **RelatedFilter boundary mixed with direct lookups** (e.g. ``role =
          RelatedFilter(...)`` plus ``Meta.fields = {"role": ["in"]}``) → fall
          back to an inline per-path subfield so the direct leaf lookups
          (``role.in``) stay queryable.  The lambda-ref optimisation is
          dropped in this case — preserves functionality at the cost of
          Apollo cache dedup for that specific field.
        * **Simple field** (everything else) → per-field operator bag type.
        """
        fields: dict[str, graphene.InputField] = {}
        related_filters = getattr(fs_class, "related_filters", {})
        trees = self.filterset_to_trees(fs_class)

        for root in trees:
            if root.name in self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES:
                fields[root.name] = self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES[root.name]()
                continue

            rel_filter = related_filters.get(root.name)
            if rel_filter is not None and isinstance(rel_filter, BaseRelatedFilter):
                target_fs = rel_filter.filterset
                # Pure RelatedFilter traversal — no direct leaves at this level.
                # Emit a lambda ref to the target filterset's root type so the
                # same target resolves to the same GraphQL type across all
                # connection fields that reach it (Apollo cache dedup).
                has_direct_leaf = any(child.height == 0 for child in root.children)
                if target_fs is not None and not has_direct_leaf:
                    target_name = target_fs.type_name_for()
                    fields[root.name] = graphene.InputField(
                        lambda tn=target_name: self.input_object_types[tn],
                        description=f"`{pascalcase(root.name)}` field",
                    )
                    continue
                # Mixed case (RelatedFilter + direct lookups): fall through
                # to the inline per-path subfield builder below.

            fields[root.name] = self._build_path_subfield(fs_class, root, root.name)

        return fields

    def _build_path_subfield(
        self,
        fs_class: type[AdvancedFilterSet],
        node: Node,
        path: str,
    ) -> graphene.InputField:
        """Build the per-path operator-bag type (``{FilterSet}{Field}FilterInputType``).

        Leaf children become lookup-expression input fields; non-leaf children
        recurse into their own per-path sub-types (covers nested transforms like
        ``created.date.year``).
        """
        fields: dict[str, graphene.InputField] = {}
        all_filters = fs_class.get_filters()

        for child in node.children:
            if child.name in self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES:
                fields[child.name] = self.SPECIAL_FILTER_INPUT_TYPES_FACTORIES[child.name]()
                continue
            if child.height == 0:
                filter_name = LOOKUP_SEP.join(
                    n.name for n in child.path if n.name != django_settings.DEFAULT_LOOKUP_EXPR
                )
                fields[child.name] = self.get_field(filter_name, all_filters[filter_name])
            else:
                child_path = f"{path}{LOOKUP_SEP}{child.name}"
                fields[child.name] = self._build_path_subfield(fs_class, child, child_path)

        type_name = fs_class.type_name_for(path)
        return graphene.InputField(
            self.create_input_object_type(type_name, fields),
            description=f"`{pascalcase(node.name)}` field",
        )

    def get_field(self, name: str, filter_obj: Filter) -> graphene.InputField:
        """Create and return a Graphene input field from a Django Filter field.

        Parameters:
        - name (str): The name of the field.
        - filter_obj (Filter): The Django Filter field.

        Returns:
        - graphene.InputField: The created Graphene input field.
        """
        model = self.filterset_class._meta.model
        filter_type: str = filter_obj.lookup_expr

        # Initialize form field directly from the filter_obj filter
        form_field = filter_obj.field

        # Handle special case when the filter_obj filter type is not 'isnull' and the name is not declared
        if filter_type != "isnull" and name not in self.filterset_class.declared_filters:
            model_field = get_model_field(model, filter_obj.field_name)
            if hasattr(model_field, "formfield"):
                form_field = model_field.formfield(required=filter_obj.extra.get("required", False))

        # Convert Django form field to Graphene field
        graphene_field = convert_form_field(form_field)

        if filter_type in ("in", "range"):
            graphene_field = graphene.List(graphene_field.get_type())

        field_type = graphene_field.InputField()
        field_type.description = getattr(
            filter_obj, "label", f"`{pascalcase(filter_obj.lookup_expr)}` lookup"
        )
        return field_type

    # THIS IS THE MAGIC
    @classmethod
    def filterset_to_trees(cls, filterset_class: type[AdvancedFilterSet]) -> list[Node]:
        """Convert a FilterSet class to a list of trees.

        where each tree represents a set of chained lookups for a filter.

        Parameters:
        - filterset_class (Type[AdvancedFilterSet]): The FilterSet class to be converted.

        Returns:
        - List[Node]: A list of root nodes for each tree, each representing a filter.
        """
        # Initialize an empty list to hold the root nodes of the trees.
        trees: list[Node] = []

        # Use .get_filters().values() instead of .base_filters.values()
        # This ensures we get the expanded related filters.
        all_filters = filterset_class.get_filters()

        # Iterate through each filter in the FilterSet's base_filters.
        for filter_value in all_filters.values():
            # Split the filter's field_name and lookup_expr into a sequence of values.
            values = (
                *filter_value.field_name.split(LOOKUP_SEP),
                filter_value.lookup_expr,
            )

            # Check if any existing tree can accommodate the new sequence of values.
            # If not, create a new tree for it.
            if not trees or not any(cls.try_add_sequence(tree, values) for tree in trees):
                trees.append(cls.sequence_to_tree(values))

        return trees

    @classmethod
    def try_add_sequence(cls, root: Node, values: Sequence[str]) -> bool:
        """Attempt to add a sequence of values to an existing tree rooted at `root`.

        Return a flag indicating whether the mutation was made.

        Parameters:
        - root (Node): The root node of the tree.
        - values (Sequence[str]): The sequence of values to add.

        Returns:
        - bool: True if the sequence was successfully added, otherwise False.
        """
        if root.name != values[0]:
            return False

        for child in root.children:
            # is mutated?
            if cls.try_add_sequence(child, values[1:]):
                return True
        # Add a new subtree rooted at `root` if the sequence could not be added to any child
        root.children = (*root.children, cls.sequence_to_tree(values[1:]))
        return True

    @staticmethod
    def sequence_to_tree(values: Sequence[str]) -> Node:
        """Convert a sequence of values into a tree, where each value becomes a node.

        Parameters:
        - values (Sequence[str]): The sequence of values.

        Returns:
        - Node: The root node of the generated tree.
        """
        if not values:
            return Node(name="")

        node: Node | None = None

        for value in values:
            node = Node(name=value, parent=node)

        return node.root
