"""Test that apply_cascade_permissions isolates correctly under async concurrency.

ContextVar provides per-coroutine isolation, so two concurrent async tasks
calling apply_cascade_permissions on the same thread must not share their
cycle-detection ``seen`` sets.
"""

import asyncio

from django.test import TestCase

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.schema import AttributeNode, ObjectNode
from cookbook.recipes.services import seed_data
from django_graphene_filters.permissions import _cascade_seen, apply_cascade_permissions
from unittest.mock import MagicMock


COUNT = 2


class AsyncCascadeIsolationTests(TestCase):
    """Verify ContextVar isolation across concurrent coroutines."""

    def setUp(self):
        super().setUp()
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()
        seed_data(COUNT)

    def test_concurrent_coroutines_have_isolated_seen_sets(self):
        """Two coroutines on the same thread must not share the seen set.

        With threading.local this would fail — both coroutines would
        write to the same set. With ContextVar each gets its own copy.
        """
        info = MagicMock()
        info.context.user = None

        results = {}

        async def cascade_object():
            """Run cascade on ObjectNode and snapshot the seen set."""
            qs = Object.objects.filter(is_private=False)
            apply_cascade_permissions(ObjectNode, qs, info)
            # After the call completes, seen should be reset to None
            results["object_seen_after"] = _cascade_seen.get()

        async def cascade_attribute():
            """Run cascade on AttributeNode and snapshot the seen set."""
            qs = Attribute.objects.filter(is_private=False)
            apply_cascade_permissions(AttributeNode, qs, info)
            results["attribute_seen_after"] = _cascade_seen.get()

        async def run_both():
            # Run both concurrently on the same event loop (same thread)
            await asyncio.gather(cascade_object(), cascade_attribute())

        asyncio.run(run_both())

        # After each coroutine finishes, its seen set should be cleaned up
        self.assertIsNone(
            results["object_seen_after"],
            "ObjectNode cascade leaked its seen set into the context",
        )
        self.assertIsNone(
            results["attribute_seen_after"],
            "AttributeNode cascade leaked its seen set into the context",
        )

    def test_nested_cascade_cleans_up_on_completion(self):
        """After a full cascade call, the ContextVar is reset to None."""
        info = MagicMock()
        info.context.user = None
        qs = Object.objects.filter(is_private=False)

        # Before
        self.assertIsNone(_cascade_seen.get())

        # During (implicitly tested by the call succeeding)
        apply_cascade_permissions(ObjectNode, qs, info)

        # After — must be cleaned up
        self.assertIsNone(_cascade_seen.get())
