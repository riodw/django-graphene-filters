from cookbook.recipes.services import TEST_USER_PASSWORD, create_users
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Create test users with individual model-view permissions. "
        "Each unit creates 5 users: 1 staff + 4 per-permission users."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "count",
            nargs="?",
            type=int,
            default=1,
            help="Number of user sets to create (default is 1 = 5 users)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        self.stdout.write(self.style.NOTICE(f"Creating {count} set(s) of test users..."))

        result = create_users(count)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done! Created {result['users']} users. " f"Password for all: {TEST_USER_PASSWORD}"
            )
        )
