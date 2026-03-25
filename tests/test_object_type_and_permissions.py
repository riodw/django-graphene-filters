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
    """Cover object_type.py lines 82-85: fallback sets FK IDs to 0."""

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
        """_make_sentinel(source_pk) with existing row copies real FK IDs (lines 79-81)."""
        ot = ObjectType.objects.create(name="test_ot")
        obj = Object.objects.create(name="test_obj", object_type=ot)
        sentinel = ObjectNode._make_sentinel(source_pk=obj.pk)
        assert sentinel.pk == 0
        assert sentinel.object_type_id == ot.pk


@pytest.mark.django_db
class TestGetNodeEdgeCases:
    """Cover object_type.py lines 110-111, 113-114, 123-132, 133."""

    def test_get_node_id_zero_returns_sentinel(self):
        """get_node(info, 0) returns a sentinel (line 110-111)."""
        info = MagicMock()
        result = ObjectNode.get_node(info, 0)
        assert result is not None
        assert result.pk == 0

    def test_get_node_id_none_returns_none(self):
        """get_node(info, None) returns None (line 113-114)."""
        info = MagicMock()
        result = ObjectNode.get_node(info, None)
        assert result is None

    def test_get_node_nonexistent_row_returns_none(self):
        """get_node for a pk that never existed returns None (line 133)."""
        info = MagicMock()
        result = ObjectNode.get_node(info, 999999)
        assert result is None

    def test_get_node_hidden_row_returns_sentinel(self):
        """get_node for a row hidden by get_queryset returns sentinel (lines 123-132)."""
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
    """Cover permissions.py lines 103-104 and 117-118."""

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
        """FK targets not registered in the graphene registry are skipped (line 78-79)."""
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
