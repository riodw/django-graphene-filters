"""Tests for object_type.py and permissions.py uncovered lines."""

from unittest.mock import MagicMock

import pytest
from cookbook.recipes.models import Object, ObjectType
from cookbook.recipes.schema import ObjectNode, ObjectTypeNode

from django_graphene_filters.permissions import apply_cascade_permissions

# ===========================================================================
# object_type.py coverage
# ===========================================================================


@pytest.mark.django_db
class TestMakeSentinelFallback:
    """``_make_sentinel`` fallback path: FK IDs default to 0 when no source PK."""

    def test_no_source_pk_sets_fk_to_zero(self):
        """_make_sentinel() with no source_pk hits the fallback branch."""
        sentinel = ObjectNode._make_sentinel()
        assert sentinel.pk == 0
        assert sentinel.object_type_id == 0

    def test_source_pk_not_found_in_db_falls_back(self):
        """_make_sentinel(source_pk=999999) where the pk doesn't exist in DB."""
        sentinel = ObjectNode._make_sentinel(source_pk=999999)
        assert sentinel.pk == 0
        assert sentinel.object_type_id == 0

    def test_no_fk_fields_model(self):
        """_make_sentinel on a model with no FK fields hits the fallback."""
        sentinel = ObjectTypeNode._make_sentinel()
        assert sentinel.pk == 0

    def test_source_pk_found_copies_fk_ids(self):
        """``_make_sentinel(source_pk)`` copies real FK IDs from the existing row."""
        ot = ObjectType.objects.create(name="test_ot")
        obj = Object.objects.create(name="test_obj", object_type=ot)
        sentinel = ObjectNode._make_sentinel(source_pk=obj.pk)
        assert sentinel.pk == 0
        assert sentinel.object_type_id == ot.pk

    def test_is_redacted_field(self):
        """resolve_is_redacted returns True for sentinels, False for real instances."""
        ot = ObjectType.objects.create(name="real_ot")
        obj = Object.objects.create(name="real_obj", object_type=ot)
        sentinel = ObjectNode._make_sentinel()

        assert ObjectNode.resolve_is_redacted(sentinel, None) is True
        assert ObjectNode.resolve_is_redacted(obj, None) is False


@pytest.mark.django_db
class TestGetNodeEdgeCases:
    """Edge cases for ``AdvancedDjangoObjectType.get_node``."""

    def test_get_node_id_zero_returns_sentinel(self):
        """``get_node(info, 0)`` returns a sentinel (FK fallback chain)."""
        info = MagicMock()
        result = ObjectNode.get_node(info, 0)
        assert result is not None
        assert result.pk == 0

    def test_get_node_id_none_returns_none(self):
        """``get_node(info, None)`` returns None."""
        info = MagicMock()
        result = ObjectNode.get_node(info, None)
        assert result is None

    def test_get_node_nonexistent_row_returns_none(self):
        """``get_node`` returns None for a pk that never existed in the table."""
        info = MagicMock()
        result = ObjectNode.get_node(info, 999999)
        assert result is None

    def test_get_node_string_zero_returns_sentinel(self):
        """get_node(info, "0") returns a sentinel (Relay global ID decodes to string)."""
        info = MagicMock()
        result = ObjectNode.get_node(info, "0")
        assert result is not None
        assert result.pk == 0

    def test_get_node_hidden_row_returns_sentinel(self):
        """``get_node`` returns a sentinel for a row hidden by ``get_queryset``."""
        ot = ObjectType.objects.create(name="hidden_ot", is_private=False)
        obj = Object.objects.create(name="hidden_obj", object_type=ot, is_private=True)

        # Anonymous user -> get_queryset returns queryset.filter(is_private=False)
        info = MagicMock()
        info.context.user = None

        result = ObjectNode.get_node(info, obj.pk)
        assert result is not None
        assert result.pk == 0
        assert result.object_type_id == ot.pk


# ===========================================================================
# permissions.py coverage
# ===========================================================================


class TestApplyCascadePermissions:
    """Tests for ``apply_cascade_permissions`` cycle detection and field filtering."""

    def test_cycle_detection_breaks_infinite_loop(self):
        from django_graphene_filters.permissions import _cascade_seen

        info = MagicMock()
        qs = Object.objects.none()

        # Pre-seed the seen set to simulate a cycle
        _cascade_seen.set({ObjectNode})
        try:
            result = apply_cascade_permissions(ObjectNode, qs, info)
            assert result is qs
        finally:
            _cascade_seen.set(None)

    def test_fields_filter_skips_non_listed_fk(self):
        info = MagicMock()
        qs = Object.objects.all()

        result = apply_cascade_permissions(ObjectNode, qs, info, fields=["nonexistent"])
        assert result is qs

    def test_skips_fk_with_no_registered_graphene_type(self):
        """FK targets not registered in the graphene registry are skipped."""
        from unittest.mock import patch

        info = MagicMock()
        qs = Object.objects.all()

        # Patch the registry to return None for all models → forces the
        # target_type is None branch.
        mock_registry = MagicMock()
        mock_registry.get_type_for_model.return_value = None
        with patch("graphene_django.registry.get_global_registry", return_value=mock_registry):
            result = apply_cascade_permissions(ObjectNode, qs, info)
        # No filters applied since no target types found
        assert result is qs
