from cookbook.recipes.services import create_people
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Bulk creates random People objects with associated values"

    def add_arguments(self, parser):
        parser.add_argument(
            "count",
            nargs="?",
            type=int,
            default=50,
            help="Number of people to create (default is 50)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        self.stdout.write(self.style.NOTICE(f"Creating {count} people..."))

        created_count = create_people(count)

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully created {created_count} people and {created_count * 3} associated values."
            )
        )
