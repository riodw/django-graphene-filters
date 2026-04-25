"""Multi-DB / sharding compatibility tests.

Exercises the alias-propagation rule described in
``docs/spec-db_sharding.md``: library-originated queries that start on a
fresh model manager must inherit the DB alias of the caller queryset
(``queryset.db`` / ``self.queryset.db``) so single-DB behaviour is
unchanged while shard-aware consumers no longer trip cross-database
subqueries or probe the wrong alias.

Covers the three in-scope fix sites:

* ``apply_cascade_permissions`` — cascade subquery is pinned to the
  caller queryset's alias.
* ``AdvancedAggregateSet.get_child_queryset`` — related-aggregate child
  queryset inherits the parent alias.
* ``AdvancedDjangoObjectType.get_node`` + ``_make_sentinel(using=...)``
  — hidden-row existence probe and sentinel FK-reload inherit the
  alias selected by ``cls.get_queryset``.

These tests require sharded mode — set the ``COOKBOOK_SHARDED=1`` env var
before running::

    COOKBOOK_SHARDED=1 uv run pytest

Under ``COOKBOOK_SHARDED=1`` Django sees two aliases: ``default`` (the
primary shard backed by ``db_shard_a.sqlite3``) and ``shard_b`` (the
secondary shard backed by ``db_shard_b.sqlite3``).  The dev
``db.sqlite3`` is invisible.  Under the default single-DB configuration
the whole module is skipped at import time so the normal suite stays
hermetic.
"""

from unittest.mock import MagicMock

import pytest
from cookbook.recipes.aggregates import ObjectTypeAggregate
from cookbook.recipes.models import Object, ObjectType
from cookbook.recipes.schema import ObjectNode
from django.conf import settings as django_settings

from django_graphene_filters.permissions import apply_cascade_permissions

# Aliases exercised by the sharded mode.  ``default`` IS shard A — see
# ``examples/cookbook/cookbook/settings.py`` for the mapping.
MULTI_DB = ["default", "shard_b"]

# Module-level gate: skip entirely when sharded mode isn't active.
# Checking ``DATABASES`` directly keeps this decoupled from the env
# var name so the tests still do the right thing under any multi-DB
# config that declares both aliases.
pytestmark = pytest.mark.skipif(
    "shard_b" not in django_settings.DATABASES,
    reason=("Requires ``shard_b`` DATABASES alias. Set ``COOKBOOK_SHARDED=1`` in the environment to enable."),
)


# ===========================================================================
# apply_cascade_permissions
# ===========================================================================


@pytest.mark.django_db(databases=MULTI_DB)
class TestCascadePermissionsAliasPropagation:
    """``apply_cascade_permissions`` pins the target-node subquery to the caller alias."""

    def test_returned_queryset_keeps_caller_alias(self):
        """Input queryset on ``shard_b`` → output queryset on ``shard_b``."""
        info = MagicMock()
        qs = Object.objects.using("shard_b").all()
        result = apply_cascade_permissions(ObjectNode, qs, info)
        assert result.db == "shard_b"

    def test_default_alias_regression(self):
        """Implicit-default path: output stays on ``default`` (shard A)."""
        info = MagicMock()
        qs = Object.objects.all()  # implicit default
        result = apply_cascade_permissions(ObjectNode, qs, info)
        assert result.db == "default"

    def test_shard_pinned_queryset_evaluates_without_cross_db_error(self):
        """Evaluating the returned queryset must not raise a cross-DB subquery error.

        Before the fix the inner ``field.related_model._default_manager.all()``
        would default to ``default`` even when the outer queryset lived on
        ``shard_b``, producing a ``ValueError`` from Django about subqueries
        across databases.
        """
        ot = ObjectType.objects.using("shard_b").create(name="shard_b_ot")
        Object.objects.using("shard_b").create(name="shard_b_obj", object_type=ot)

        info = MagicMock()
        info.context.user = None
        qs = Object.objects.using("shard_b").filter(is_private=False)
        result = apply_cascade_permissions(ObjectNode, qs, info)

        # Force evaluation — any cross-DB subquery would raise here.
        names = list(result.values_list("name", flat=True))
        assert "shard_b_obj" in names


# ===========================================================================
# AdvancedAggregateSet.get_child_queryset
# ===========================================================================


@pytest.mark.django_db(databases=MULTI_DB)
class TestRelatedAggregateAliasInheritance:
    """``get_child_queryset`` pins the child queryset to the parent alias."""

    def test_child_queryset_inherits_shard_alias(self):
        parent_qs = ObjectType.objects.using("shard_b").all()
        agg = ObjectTypeAggregate(queryset=parent_qs, request=None)
        rel_agg = agg.related_aggregates["objects"]

        child_qs = agg.get_child_queryset("objects", rel_agg)
        assert child_qs.db == "shard_b"

    def test_child_queryset_default_alias_regression(self):
        parent_qs = ObjectType.objects.all()  # implicit default (shard A)
        agg = ObjectTypeAggregate(queryset=parent_qs, request=None)
        rel_agg = agg.related_aggregates["objects"]

        child_qs = agg.get_child_queryset("objects", rel_agg)
        assert child_qs.db == "default"


# ===========================================================================
# AdvancedDjangoObjectType._make_sentinel(using=...)
# ===========================================================================


@pytest.mark.django_db(databases=MULTI_DB)
class TestMakeSentinelUsingKwarg:
    """``_make_sentinel(using=alias)`` reloads FK IDs from the named alias."""

    def test_reload_from_shard_copies_fk_ids(self):
        """FK IDs are read from ``shard_b`` even though no row exists on ``default``."""
        ot = ObjectType.objects.using("shard_b").create(name="shard_b_ot")
        obj = Object.objects.using("shard_b").create(name="shard_b_obj", object_type=ot)

        sentinel = ObjectNode._make_sentinel(source_pk=obj.pk, using="shard_b")
        assert sentinel.pk == 0
        assert sentinel.object_type_id == ot.pk

    def test_without_using_falls_back_when_row_absent_from_default(self):
        """Without ``using``, FK reload hits default — row missing there → fallback."""
        ot = ObjectType.objects.using("shard_b").create(name="only_on_shard_b")
        obj = Object.objects.using("shard_b").create(name="only_on_shard_b_obj", object_type=ot)

        # Row exists on shard_b but NOT on default. Without using=, the reload
        # probe runs on default and returns None → fallback to FK=0.
        sentinel = ObjectNode._make_sentinel(source_pk=obj.pk)
        assert sentinel.pk == 0
        assert sentinel.object_type_id == 0

    def test_using_kwarg_is_keyword_only(self):
        """``using`` must be passed by keyword (forward-compatible API)."""
        with pytest.raises(TypeError):
            # Positional use is rejected by the keyword-only marker.
            ObjectNode._make_sentinel(1, "shard_b")  # type: ignore[misc]


# ===========================================================================
# AdvancedDjangoObjectType.get_node alias threading
# ===========================================================================


@pytest.mark.django_db(databases=MULTI_DB)
class TestGetNodeAliasThreading:
    """``get_node`` threads the alias of the consumer's ``get_queryset`` result."""

    def test_hidden_row_on_shard_returns_sentinel(self, monkeypatch):
        """A row hidden by ``get_queryset`` on ``shard_b`` resolves to a sentinel.

        The existence probe must hit ``shard_b`` (not ``default``) to detect
        that the row really exists but was filtered out. If the probe ran
        on the default alias (old behaviour) the row would be absent, the
        sentinel branch would not fire, and ``get_node`` would return
        ``None`` instead.
        """
        ot = ObjectType.objects.using("shard_b").create(name="ot_on_shard_b")
        obj = Object.objects.using("shard_b").create(
            name="private_obj_on_shard_b",
            object_type=ot,
            is_private=True,
        )

        # Override ObjectNode.get_queryset so it shards to ``shard_b`` and
        # hides private rows — simulating a consumer's shard-aware policy.
        def shard_aware_get_queryset(cls, queryset, info):
            return queryset.using("shard_b").filter(is_private=False)

        monkeypatch.setattr(
            ObjectNode,
            "get_queryset",
            classmethod(shard_aware_get_queryset),
        )

        info = MagicMock()
        info.context.user = None

        result = ObjectNode.get_node(info, obj.pk)
        assert result is not None, "get_node should return a sentinel, not None"
        assert result.pk == 0
        # Sentinel copies the real FK IDs from shard_b.
        assert result.object_type_id == ot.pk
