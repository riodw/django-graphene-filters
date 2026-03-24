from cookbook.recipes.services import delete_users
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Delete test users (never deletes superusers). "
        "Pass an integer to delete the first N users, "
        'or "all" to delete all non-superusers.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "target",
            type=str,
            help='Number of users to delete or "all"',
        )

    def handle(self, *args, **options):
        target = options["target"]

        if target != "all":
            try:
                count = int(target)
                if count < 1:
                    self.stderr.write(self.style.ERROR("Count must be a positive integer."))
                    return
            except ValueError:
                self.stderr.write(
                    self.style.ERROR(f'Invalid target "{target}". Use a positive integer or "all".')
                )
                return

        self.stdout.write(self.style.NOTICE(f"Deleting users (target={target})..."))

        result = delete_users(target)

        if result["users"]:
            self.stdout.write(self.style.SUCCESS(f"Deleted {result['users']} users."))
        else:
            self.stdout.write(self.style.WARNING("Nothing to delete."))
