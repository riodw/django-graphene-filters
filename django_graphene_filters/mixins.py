"""Shared mixins for filters and orders."""

from typing import Any, cast

import graphene
from django.db import models
from django.utils.module_loading import import_string


def get_concrete_field_names(model: type[models.Model]) -> list[str]:
    """Return the names of all concrete (column-backed) fields on a Django model.

    This excludes reverse relations, many-to-many managers, and other virtual fields.
    """
    return [f.name for f in model._meta.get_fields() if hasattr(f, "column")]


class LazyRelatedClassMixin:
    """Mixin providing utilities to lazily resolve class imports by string paths.

    This is extremely useful when defining related classes inline to avoid circular imports.
    """

    def resolve_lazy_class(self, class_ref: Any, bound_class: type | None) -> Any:
        """Resolve a class reference.

        If it's a string, attempts absolute import and falls back to relative import
        using the bound class's module. If callable (but not a class type), executes it.
        Otherwise, returns it as-is.
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
    """Mixin for dynamically creating and caching Graphene InputObjectTypes."""

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

    Unlike ``InputObjectTypeFactoryMixin`` which creates input types for filters/orders,
    this creates output types suitable for aggregate result schemas.
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
