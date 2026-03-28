import graphene
from graphql import GraphQLError

import django_graphene_filters as fieldsets

from . import models


def _user(info):
    """Extract the user from info.context, or None."""
    return getattr(info.context, "user", None)


def _resolve_date(dt, info, perm):
    """Tiered date visibility.

    Staff         → full ISO datetime
    view_<model>  → year-month-day
    Authenticated → year-month
    Anonymous     → year only
    """
    user = _user(info)
    if user and user.is_staff:
        return dt.isoformat()
    if user and user.has_perm(perm):
        return dt.strftime("%Y-%m-%d")
    if user and user.is_authenticated:
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y")


# ---------------------------------------------------------------------------
# ObjectType
# ---------------------------------------------------------------------------


class ObjectTypeFieldSet(fieldsets.AdvancedFieldSet):
    display_name = graphene.String(description="Computed: {id} - {name}")

    class Meta:
        model = models.ObjectType

    def resolve_description(self, root, info):
        """Staff sees description; non-staff gets empty string."""
        user = _user(info)
        if user and user.is_staff:
            return root.description
        return ""

    def resolve_display_name(self, root, info):
        """Computed field: '{id} - {name}'. Visible to all signed-in users."""
        user = _user(info)
        if user and user.is_authenticated:
            return f"{root.id} - {root.name}"
        return None

    def resolve_created_date(self, root, info):
        return _resolve_date(root.created_date, info, "recipes.view_objecttype")

    def check_updated_date_permission(self, info):
        """Gate: anonymous users cannot see updated_date at all."""
        user = _user(info)
        if not user or not user.is_authenticated:
            raise GraphQLError("Login required to view updated date.")

    def resolve_updated_date(self, root, info):
        return _resolve_date(root.updated_date, info, "recipes.view_objecttype")


# ---------------------------------------------------------------------------
# Object
# ---------------------------------------------------------------------------


class ObjectFieldSet(fieldsets.AdvancedFieldSet):
    display_name = graphene.String(description="Computed: {id} - {name}")

    class Meta:
        model = models.Object

    def resolve_is_private(self, root, info):
        """Staff sees is_private; non-staff gets False."""
        user = _user(info)
        if user and user.is_staff:
            return root.is_private
        return False

    def resolve_display_name(self, root, info):
        """Computed field: '{id} - {name}'. Visible to all signed-in users."""
        user = _user(info)
        if user and user.is_authenticated:
            return f"{root.id} - {root.name}"
        return None

    def resolve_created_date(self, root, info):
        return _resolve_date(root.created_date, info, "recipes.view_object")

    def check_updated_date_permission(self, info):
        """Gate: anonymous users cannot see updated_date."""
        user = _user(info)
        if not user or not user.is_authenticated:
            raise GraphQLError("Login required to view updated date.")

    def resolve_updated_date(self, root, info):
        return _resolve_date(root.updated_date, info, "recipes.view_object")


# ---------------------------------------------------------------------------
# Attribute
# ---------------------------------------------------------------------------


class AttributeFieldSet(fieldsets.AdvancedFieldSet):
    display_name = graphene.String(description="Computed: {id} - {name}")

    class Meta:
        model = models.Attribute

    def resolve_display_name(self, root, info):
        """Computed field: '{id} - {name}'. Visible to all signed-in users."""
        user = _user(info)
        if user and user.is_authenticated:
            return f"{root.id} - {root.name}"
        return None

    def resolve_created_date(self, root, info):
        return _resolve_date(root.created_date, info, "recipes.view_attribute")

    def check_updated_date_permission(self, info):
        """Gate: anonymous users cannot see updated_date."""
        user = _user(info)
        if not user or not user.is_authenticated:
            raise GraphQLError("Login required to view updated date.")

    def resolve_updated_date(self, root, info):
        return _resolve_date(root.updated_date, info, "recipes.view_attribute")


# ---------------------------------------------------------------------------
# Value
# ---------------------------------------------------------------------------


class ValueFieldSet(fieldsets.AdvancedFieldSet):
    display_name = graphene.String(description="Computed: {id} - {value}")

    class Meta:
        model = models.Value

    def resolve_display_name(self, root, info):
        """Computed field: '{id} - {value}'. Visible to all signed-in users."""
        user = _user(info)
        if user and user.is_authenticated:
            return f"{root.id} - {root.value}"
        return None

    def resolve_created_date(self, root, info):
        return _resolve_date(root.created_date, info, "recipes.view_value")

    def check_updated_date_permission(self, info):
        """Gate: anonymous users cannot see updated_date."""
        user = _user(info)
        if not user or not user.is_authenticated:
            raise GraphQLError("Login required to view updated date.")

    def resolve_updated_date(self, root, info):
        return _resolve_date(root.updated_date, info, "recipes.view_value")
