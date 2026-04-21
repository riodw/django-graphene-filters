"""Shared mixins for filters and orders."""

from typing import Any, cast

import graphene
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from django.utils.module_loading import import_string
from stringcase import pascalcase


def get_concrete_field_names(model: type[models.Model]) -> list[str]:
    """Return the names of all concrete (column-backed) fields on a Django model.

    Uses ``hasattr(f, "column")`` rather than ``f.concrete`` because
    Django's ``concrete`` attribute is ``True`` for ``ManyToManyField``
    (which has no column on the model's table).  The ``column`` attribute
    only exists on fields that map to a single DB column — ``ForeignKey``,
    ``OneToOneField``, ``CharField``, ``IntegerField``, etc.

    This excludes reverse relations, many-to-many managers, and other
    virtual fields.
    """
    return [f.name for f in model._meta.get_fields() if hasattr(f, "column")]


class ClassBasedTypeNameMixin:
    """Contribute a ``type_name_for()`` classmethod for class-based GraphQL naming.

    Subclasses set two class attributes:

    * ``_root_type_suffix`` — appended to ``cls.__name__`` for the root type
      (e.g. ``"InputType"``, ``"Type"``).
    * ``_field_type_suffix`` — appended after a pascal-cased field path for
      per-field operator bags (e.g. ``"FilterInputType"``, ``"Type"``).

    The single implementation handles both simple field names (``"name"``)
    and ``LOOKUP_SEP``-separated nested paths (``"created__date__year"``).
    See ``docs/spec-base_type_naming.md`` for the naming spec.
    """

    _root_type_suffix: str = "InputType"
    _field_type_suffix: str = "InputType"

    @classmethod
    def type_name_for(cls, field_path: str | None = None) -> str:
        """Return the GraphQL type name for this class or a sub-field path."""
        if field_path is None:
            return f"{cls.__name__}{cls._root_type_suffix}"
        parts = field_path.split(LOOKUP_SEP)
        pascal = "".join(pascalcase(p) for p in parts)
        return f"{cls.__name__}{pascal}{cls._field_type_suffix}"


class LazyRelatedClassMixin:
    """Mixin providing utilities to lazily resolve class imports by string paths.

    This is extremely useful when defining related classes inline to avoid circular imports.
    """

    def resolve_lazy_class(self, class_ref: Any, bound_class: type | None) -> Any:
        """Resolve a class reference.

        String references are resolved in two steps:
        1. Try as an absolute import path (e.g. ``"myapp.filters.MyFilter"``)
        2. On ``ImportError``, fall back to ``bound_class.__module__ + "." + class_ref``
           (e.g. ``"MyFilter"`` → ``"myapp.filters.MyFilter"`` if bound to a
           class in ``myapp.filters``)

        Callables (but not class types) are invoked as zero-arg factories.
        Everything else is returned as-is.
        """
        if isinstance(class_ref, str):
            try:
                # Assume absolute import path
                return import_string(class_ref)
            except ImportError:
                # Fallback to building import path relative to bound class
                if bound_class:
                    path = ".".join([bound_class.__module__, class_ref])
                    return import_string(path)
                raise
        elif callable(class_ref) and not isinstance(class_ref, type):
            return class_ref()
        return class_ref


class InputObjectTypeFactoryMixin:
    """Mixin for dynamically creating and caching Graphene InputObjectTypes.

    The cache is keyed by type **name** only.  Callers must ensure unique
    names (e.g. via a prefix derived from the node type + class name) to
    avoid collisions.  ``FilterArgumentsFactory`` defines its own
    ``input_object_types`` dict to isolate filter types from order types.
    """

    input_object_types: dict[str, type[graphene.InputObjectType]] = {}

    @classmethod
    def create_input_object_type(
        cls,
        name: str,
        fields: dict[str, Any],
    ) -> type[graphene.InputObjectType]:
        """Create a new GraphQL type inheritor inheriting from `graphene.InputObjectType`.

        Uses a shared cache to avoid duplicating types with the same name.
        """
        if name in cls.input_object_types:
            return cls.input_object_types[name]

        cls.input_object_types[name] = cast(
            type[graphene.InputObjectType],
            type(
                name,
                (graphene.InputObjectType,),
                fields,
            ),
        )
        return cls.input_object_types[name]


class ObjectTypeFactoryMixin:
    """Mixin for dynamically creating and caching Graphene ObjectTypes (output types).

    Unlike ``InputObjectTypeFactoryMixin`` which creates input types for
    filters/orders, this creates output types suitable for aggregate result
    schemas.  The cache is keyed by type **name** only — callers must
    ensure unique names via prefixes.
    """

    object_types: dict[str, type[graphene.ObjectType]] = {}

    @classmethod
    def create_object_type(
        cls,
        name: str,
        fields: dict[str, Any],
    ) -> type[graphene.ObjectType]:
        """Create a new GraphQL output type inheriting from `graphene.ObjectType`.

        Uses a shared cache to avoid duplicating types with the same name.
        """
        if name in cls.object_types:
            return cls.object_types[name]

        cls.object_types[name] = cast(
            type[graphene.ObjectType],
            type(
                name,
                (graphene.ObjectType,),
                fields,
            ),
        )
        return cls.object_types[name]
