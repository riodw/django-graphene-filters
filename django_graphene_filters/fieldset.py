"""`AdvancedFieldSet` class module.

Provides resolve-time field-level permissions and content overrides.
Consumers declare ``check_<field>_permission(info)`` methods to gate
field visibility, and ``resolve_<field>(root, info)`` methods to
override field content (masking, computed values, role-based output).

The cascade order is:
1. ``check_<field>_permission`` — gate (raises → denied, doesn't raise → continue).
   Denied fields return a type-appropriate default (``None`` for nullable,
   ``""`` for text, ``False`` for boolean, epoch for datetime, etc.).
2. ``resolve_<field>`` — content override (can assume check passed)
3. Default resolver — ``getattr(root, field_name)``
"""

from typing import Any

from graphene.types.unmountedtype import UnmountedType

from .mixins import get_concrete_field_names


class FieldSetMetaclass(type):
    """Metaclass that discovers permission and resolve methods at class creation time."""

    def __new__(
        cls: type["FieldSetMetaclass"],
        name: str,
        bases: tuple,
        attrs: dict[str, Any],
    ) -> "FieldSetMetaclass":
        """Create a new FieldSet class and populate ``_managed_fields``."""
        new_class = super().__new__(cls, name, bases, attrs)
        meta = getattr(new_class, "Meta", None)

        if meta and getattr(meta, "model", None):
            model = meta.model
            model_field_names = set(get_concrete_field_names(model))

            # 1. Discover check_<field>_permission methods
            field_permissions: set[str] = set()
            for attr_name in dir(new_class):
                if attr_name.startswith("check_") and attr_name.endswith("_permission"):
                    field_name = attr_name[6:-11]  # strip check_ and _permission
                    if field_name in model_field_names:
                        field_permissions.add(field_name)

            # 2. Discover resolve_<field> methods
            # resolve_ may target computed fields not on the model —
            # skip model validation for those; they must be declared
            # on the ObjectType as graphene fields.
            field_resolvers: set[str] = set()
            for attr_name in dir(new_class):
                if attr_name.startswith("resolve_") and attr_name != "resolve_field":
                    field_name = attr_name[8:]  # strip resolve_
                    field_resolvers.add(field_name)

            # 3. Discover computed field declarations (graphene types as class attrs).
            # Uses dir(new_class) so declarations on mixin/base classes are
            # inherited — not just attrs (which only has the current class body).
            computed_fields: dict[str, Any] = {}
            for attr_name in dir(new_class):
                if attr_name.startswith("_"):
                    continue
                attr_value = getattr(new_class, attr_name, None)
                if isinstance(attr_value, UnmountedType):
                    computed_fields[attr_name] = attr_value

            # 4. Store validated config.
            # _managed_fields includes computed fields so they get the
            # permission/deny-value wrapper in _wrap_field_resolvers.
            new_class._field_permissions = field_permissions
            new_class._field_resolvers = field_resolvers
            new_class._computed_fields = computed_fields
            new_class._managed_fields = field_permissions | field_resolvers | set(computed_fields)

        return new_class


class AdvancedFieldSet(metaclass=FieldSetMetaclass):
    """Base class for field-level permissions and content overrides.

    Consumers subclass this and define:
    - ``check_<field>_permission(info)`` — permission gate (raise to deny)
    - ``resolve_<field>(root, info)`` — content override / computed field
    """

    # Default Meta — consumers override this.
    _field_permissions: set[str] = set()
    _field_resolvers: set[str] = set()
    _computed_fields: dict[str, Any] = {}
    _managed_fields: set[str] = set()

    class Meta:
        """Default Meta — consumers override this."""

        model = None

    def __init__(self, info: Any) -> None:
        self.info = info
        self.request = info.context

    def check_field(self, field_name: str) -> bool:
        """Check if the current user can see the given field.

        Returns True if allowed, False if denied.
        """
        method = getattr(self, f"check_{field_name}_permission", None)
        if method is None:
            return True  # No restriction
        try:
            method(self.info)
            return True
        except Exception:
            return False

    def has_resolve_method(self, field_name: str) -> bool:
        """Check if a ``resolve_<field>`` override exists."""
        return field_name in self._field_resolvers

    def resolve_field(self, field_name: str, root: Any, info: Any) -> Any:
        """Call the ``resolve_<field>`` override for custom content."""
        method = getattr(self, f"resolve_{field_name}")
        return method(root, info)
