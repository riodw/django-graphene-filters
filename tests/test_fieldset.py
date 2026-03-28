"""Unit tests for fieldset.py and _wrap_field_resolvers in object_type.py."""

import logging
from unittest.mock import MagicMock

from django.db import models
from graphql import GraphQLError

from django_graphene_filters.fieldset import AdvancedFieldSet

# ---------------------------------------------------------------------------
# Test model (reuse the recipes model via app_label)
# ---------------------------------------------------------------------------


class FieldSetTestModel(models.Model):
    name = models.CharField(max_length=100)
    email = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    class Meta:
        app_label = "recipes"


# ---------------------------------------------------------------------------
# FieldSetMetaclass — discovery and validation
# ---------------------------------------------------------------------------


def test_metaclass_discovers_check_permission_methods():
    """check_<field>_permission methods are discovered and stored in _field_permissions."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            pass

        def check_email_permission(self, info):
            pass

    assert TestFS._field_permissions == {"name", "email"}
    assert "name" in TestFS._managed_fields
    assert "email" in TestFS._managed_fields


def test_metaclass_discovers_resolve_methods():
    """resolve_<field> methods are discovered and stored in _field_resolvers."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def resolve_name(self, root, info):
            return "custom"

    assert TestFS._field_resolvers == {"name"}
    assert "name" in TestFS._managed_fields


def test_metaclass_discovers_both():
    """Both check_ and resolve_ for same and different fields."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_email_permission(self, info):
            pass

        def resolve_email(self, root, info):
            return "masked"

        def resolve_description(self, root, info):
            return "custom desc"

    assert TestFS._field_permissions == {"email"}
    assert TestFS._field_resolvers == {"email", "description"}
    assert TestFS._managed_fields == {"email", "description"}


def test_metaclass_ignores_non_model_fields_for_permissions():
    """check_ methods for fields not on the model are ignored."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_nonexistent_field_permission(self, info):
            pass

    assert TestFS._field_permissions == set()
    assert TestFS._managed_fields == set()


def test_metaclass_allows_resolve_for_computed_fields():
    """resolve_ methods for computed (non-model) fields are allowed."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def resolve_display_name(self, root, info):
            return "computed"

    assert "display_name" in TestFS._field_resolvers
    assert "display_name" in TestFS._managed_fields


def test_metaclass_no_model_is_noop():
    """FieldSet without Meta.model should not crash."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = None

    assert TestFS._managed_fields == set()


def test_metaclass_excludes_resolve_field_method():
    """The base resolve_field method should not be treated as a resolve_ override."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

    # resolve_field is a method on the base class, not a field resolver
    assert "field" not in TestFS._field_resolvers


# ---------------------------------------------------------------------------
# check_field — permission gate
# ---------------------------------------------------------------------------


def test_check_field_no_method_returns_true():
    """No check_ method → unrestricted."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

    info = MagicMock()
    fs = TestFS(info)
    assert fs.check_field("name") is True


def test_check_field_method_passes():
    """check_ doesn't raise → allowed."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            pass  # no exception

    info = MagicMock()
    fs = TestFS(info)
    assert fs.check_field("name") is True


def test_check_field_method_raises():
    """check_ raises → denied."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            raise GraphQLError("Denied")

    info = MagicMock()
    fs = TestFS(info)
    assert fs.check_field("name") is False


# ---------------------------------------------------------------------------
# has_resolve_method / resolve_field
# ---------------------------------------------------------------------------


def test_has_resolve_method():
    """has_resolve_method returns True when resolve_ exists."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def resolve_name(self, root, info):
            return "custom"

    info = MagicMock()
    fs = TestFS(info)
    assert fs.has_resolve_method("name") is True
    assert fs.has_resolve_method("email") is False


def test_resolve_field_calls_method():
    """resolve_field delegates to the resolve_ method."""

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def resolve_name(self, root, info):
            return f"Hello {root.name}"

    info = MagicMock()
    root = MagicMock()
    root.name = "Alice"
    fs = TestFS(info)
    assert fs.resolve_field("name", root, info) == "Hello Alice"


# ---------------------------------------------------------------------------
# _wrap_field_resolvers — cascade behaviour
# ---------------------------------------------------------------------------


def test_wrap_field_resolvers_warning_for_missing_field(caplog):
    """Warning logged when FieldSet references a field not on the node."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            pass

    node_cls = MagicMock()
    node_cls._meta.fields = {}  # no fields at all
    node_cls.__name__ = "TestNode"

    with caplog.at_level(logging.WARNING):
        _wrap_field_resolvers(node_cls, TestFS)

    assert "references field 'name'" in caplog.text


def test_wrap_field_resolvers_empty_managed_fields():
    """No-op when _managed_fields is empty."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

    node_cls = MagicMock()
    _wrap_field_resolvers(node_cls, TestFS)
    # Should not crash or modify anything


def test_wrap_cascade_check_denies_no_resolve():
    """Step 1: check denies, no resolve_ → null."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            raise GraphQLError("No")

    graphene_field = MagicMock()
    graphene_field.resolver = None

    node_cls = MagicMock()
    node_cls._meta.fields = {"name": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    root = MagicMock()
    root.name = "Alice"
    info = MagicMock()

    result = wrapper(root, info)
    assert result == ""  # denied — CharField default


def test_wrap_cascade_check_denies_with_resolve_does_not_run():
    """Step 1: check denies → gate is absolute, resolve_ does NOT run."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            raise GraphQLError("No")

        def resolve_name(self, root, info):
            return "should not reach"

    graphene_field = MagicMock()
    graphene_field.resolver = None
    # Simulate a nullable field (type is not NonNull)
    graphene_field.type = MagicMock()

    node_cls = MagicMock()
    node_cls._meta.fields = {"name": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    root = MagicMock()
    info = MagicMock()

    result = wrapper(root, info)
    # Gate denied → deny_value (CharField default), resolve_ never called
    assert result == ""


def test_wrap_non_nullable_field_denied_returns_default():
    """Non-nullable field denied by gate returns type-appropriate default, not None."""
    from django_graphene_filters.object_type import _deny_value_cache, _get_deny_value, _wrap_field_resolvers

    # Clear cache so previous test runs don't interfere
    _deny_value_cache.clear()

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            raise GraphQLError("No")

    graphene_field = MagicMock()
    graphene_field.resolver = None

    node_cls = MagicMock()
    node_cls._meta.fields = {"name": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    result = wrapper(MagicMock(), MagicMock())
    assert result == ""  # CharField default

    # Verify _get_deny_value directly using Django model fields
    # CharField → ""
    assert _get_deny_value(FieldSetTestModel, "name") == ""
    # TextField(default="") → ""
    assert _get_deny_value(FieldSetTestModel, "description") == ""

    # Test with a model that has diverse field types
    class DiverseModel(models.Model):
        flag = models.BooleanField(default=False)
        count = models.IntegerField(default=0)
        score = models.FloatField(default=0.0)
        created = models.DateTimeField(auto_now_add=True)
        updated_date = models.DateField(auto_now=True)
        birthday = models.DateField(null=True)
        uid = models.UUIDField()

        class Meta:
            app_label = "recipes"

    _deny_value_cache.clear()

    assert _get_deny_value(DiverseModel, "flag") is False
    assert _get_deny_value(DiverseModel, "count") == 0
    assert _get_deny_value(DiverseModel, "score") == 0.0

    # auto_now_add DateTimeField → epoch datetime fallback
    dt_deny = _get_deny_value(DiverseModel, "created")
    assert dt_deny is not None
    assert dt_deny.year == 1970

    # auto_now DateField → epoch date fallback
    date_deny = _get_deny_value(DiverseModel, "updated_date")
    assert date_deny is not None
    assert date_deny.year == 1970

    # Nullable field → None
    assert _get_deny_value(DiverseModel, "birthday") is None

    # Non-nullable, non-date, no default → None (fall-through)
    assert _get_deny_value(DiverseModel, "uid") is None

    # Unknown field → None
    assert _get_deny_value(DiverseModel, "nonexistent") is None

    _deny_value_cache.clear()


def test_wrap_cascade_check_passes_resolve_runs():
    """Step 1 passes → Step 2: resolve runs."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            pass  # allowed

        def resolve_name(self, root, info):
            return "masked"

    graphene_field = MagicMock()
    graphene_field.resolver = None

    node_cls = MagicMock()
    node_cls._meta.fields = {"name": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    root = MagicMock()
    info = MagicMock()

    result = wrapper(root, info)
    assert result == "masked"


def test_wrap_cascade_no_check_resolve_runs():
    """No check → Step 2: resolve runs directly."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def resolve_name(self, root, info):
            return "computed"

    graphene_field = MagicMock()
    graphene_field.resolver = None

    node_cls = MagicMock()
    node_cls._meta.fields = {"name": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    root = MagicMock()
    info = MagicMock()

    result = wrapper(root, info)
    assert result == "computed"


def test_wrap_cascade_check_passes_default_resolver():
    """Step 1 passes, no resolve → Step 3: default resolver."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            pass  # allowed

    graphene_field = MagicMock()
    graphene_field.resolver = None  # no original resolver

    node_cls = MagicMock()
    node_cls._meta.fields = {"name": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    root = MagicMock()
    root.name = "Alice"
    info = MagicMock()

    result = wrapper(root, info)
    assert result == "Alice"


def test_wrap_cascade_preserves_original_resolver():
    """Step 3: original resolver is called when no resolve_ override exists."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    original = MagicMock(return_value="from_original")

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_name_permission(self, info):
            pass

    graphene_field = MagicMock()
    graphene_field.resolver = original

    node_cls = MagicMock()
    node_cls._meta.fields = {"name": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    root = MagicMock()
    info = MagicMock()

    result = wrapper(root, info)
    assert result == "from_original"
    original.assert_called_once()


def test_wrap_camel_case_field_lookup():
    """Fields stored under camelCase key in _meta.fields are found."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = FieldSetTestModel

        def check_description_permission(self, info):
            raise GraphQLError("No")

    graphene_field = MagicMock()
    graphene_field.resolver = None

    node_cls = MagicMock()
    # graphene stores it as camelCase
    node_cls._meta.fields = {"description": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    root = MagicMock()
    info = MagicMock()

    result = wrapper(root, info)
    assert result == ""  # denied — TextField default


def test_computed_field_injection():
    """Computed fields declared on FieldSet are injected into node meta_fields."""
    import graphene

    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        display_name = graphene.String(description="computed")

        class Meta:
            model = FieldSetTestModel

        def resolve_display_name(self, root, info):
            return "test"

    node_cls = MagicMock()
    node_cls._meta.fields = {}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    # Field was injected under camelCase key
    assert "displayName" in node_cls._meta.fields


def test_computed_field_not_injected_if_already_exists():
    """Computed field injection skips if the field already exists on the node."""
    import graphene

    from django_graphene_filters.object_type import _wrap_field_resolvers

    class TestFS(AdvancedFieldSet):
        name = graphene.String(description="should not overwrite")

        class Meta:
            model = FieldSetTestModel

        def resolve_name(self, root, info):
            return "custom"

    existing_field = MagicMock()
    existing_field.resolver = None
    node_cls = MagicMock()
    node_cls._meta.fields = {"name": existing_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    # The existing field should NOT be replaced by the computed field
    assert node_cls._meta.fields["name"] is existing_field


def test_wrap_snake_case_fallback():
    """If camelCase key not found, falls back to snake_case."""
    from django_graphene_filters.object_type import _wrap_field_resolvers

    class SnakeModel(models.Model):
        first_name = models.CharField(max_length=100)

        class Meta:
            app_label = "recipes"

    class TestFS(AdvancedFieldSet):
        class Meta:
            model = SnakeModel

        def check_first_name_permission(self, info):
            raise GraphQLError("No")

    graphene_field = MagicMock()
    graphene_field.resolver = None

    node_cls = MagicMock()
    # Not stored under firstName (camelCase), but under first_name (snake_case)
    node_cls._meta.fields = {"first_name": graphene_field}
    node_cls.__name__ = "TestNode"

    _wrap_field_resolvers(node_cls, TestFS)

    wrapper = graphene_field.resolver
    assert wrapper(MagicMock(), MagicMock()) == ""  # denied — CharField default
