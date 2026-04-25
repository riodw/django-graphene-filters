"""Populate the shard SQLite DBs used by the multi-DB / stress-test flow.

Purpose
-------
Create (or refresh) ``db_shard_a.sqlite3`` and ``db_shard_b.sqlite3`` as
committed, minimal-but-realistic shard DBs.  This gives the sharded
mode a concrete, repeatable starting state and provides a foundation
for stress-testing the package at hundreds-of-thousands of rows without
DB I/O being the bottleneck.

Mode isolation
--------------
Under ``COOKBOOK_SHARDED=1`` Django sees **only** the shard DBs — the
dev ``db.sqlite3`` is invisible.  The sharded ``DATABASES`` dict has
two aliases:

* ``default``  → ``db_shard_a.sqlite3`` (primary shard; Django's
                 required ``default`` entry IS shard A)
* ``shard_b``  → ``db_shard_b.sqlite3`` (secondary shard)

What this command does (per shard alias)
----------------------------------------
1. Runs ``migrate`` on the shard so the schema exists.
2. Creates a canonical set of test users on the shard via
   :func:`create_users(count=1, db_alias=alias)`.  Each shard gets its
   own independent user population — there's no cross-DB dump/load
   because ``db.sqlite3`` is not accessible in sharded mode.
3. Calls :func:`seed_data(count, db_alias=alias)` with ``--count 1`` by
   default so there's at least one ``Object`` per Faker provider to
   exercise the filter / order / aggregate paths.

Usage
-----
Requires the ``COOKBOOK_SHARDED=1`` env var so ``settings.py`` registers
the shard aliases::

    COOKBOOK_SHARDED=1 uv run python examples/cookbook/manage.py seed_shards

Re-run at any time — every step is idempotent (migrations no-op,
create_users is idempotent by username, seed_data only creates the
shortfall).

Stress testing
--------------
Once the shards are materialized you can point a stress harness
directly at them under the same env var.  The shard files are not
touched by the test suite (Django creates separate
``test_db_shard_*.sqlite3`` files during pytest), so growing them with
millions of rows for load testing is safe::

    COOKBOOK_SHARDED=1 uv run python examples/cookbook/manage.py seed_shards --count 5000
"""

from cookbook.recipes.services import create_users, seed_data
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

# Aliases in sharded mode.  ``default`` IS shard A (Django requires a
# ``default`` entry in DATABASES); ``shard_b`` is the explicit secondary.
SHARD_ALIASES = ("default", "shard_b")


class Command(BaseCommand):
    help = (
        "Migrate, create users, and seed the shard SQLite DBs "
        "(default → shard A, shard_b). Requires COOKBOOK_SHARDED=1 in the environment."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--count",
            type=int,
            default=1,
            help="Number of Object instances per Faker provider per shard (default: 1)",
        )

    def handle(self, *args, **options) -> None:
        count = options["count"]

        # Fail fast if the sharded mode isn't active.
        if "shard_b" not in settings.DATABASES:
            raise CommandError(
                "Shard alias `shard_b` not declared in DATABASES. "
                "Set `COOKBOOK_SHARDED=1` in the environment so settings.py "
                "selects the sharded DATABASES layout."
            )

        # 1. Migrate each shard (creates schema + auth tables).
        for alias in SHARD_ALIASES:
            self.stdout.write(self.style.NOTICE(f"[{alias}] migrate"))
            call_command("migrate", database=alias, interactive=False, verbosity=0)

        # 2. Create users directly on each shard.  In single-DB mode the
        #    dev ``db.sqlite3`` has its own users; here, because Django
        #    cannot see ``db.sqlite3``, each shard gets its own
        #    freshly-seeded user set via create_users().  It's idempotent
        #    by username so re-runs are safe.
        for alias in SHARD_ALIASES:
            self.stdout.write(self.style.NOTICE(f"[{alias}] create_users"))
            user_result = create_users(count=1, db_alias=alias)
            self.stdout.write(f"  {alias}: {user_result['users']} users")

        # 3. Seed recipes content on each shard.
        for alias in SHARD_ALIASES:
            self.stdout.write(self.style.NOTICE(f"[{alias}] seed_data(count={count})"))
            result = seed_data(count, db_alias=alias)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  {alias}: {result['object_types']} object_types, "
                    f"{result['attributes']} attributes, "
                    f"{result['objects']} objects, {result['values']} values"
                )
            )

        self.stdout.write(self.style.SUCCESS("Shards populated."))
