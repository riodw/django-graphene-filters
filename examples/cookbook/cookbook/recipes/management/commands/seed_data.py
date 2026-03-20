from cookbook.recipes.services import create_data
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensures at least N objects exist per Faker provider (only creates the shortfall)"

    def add_arguments(self, parser):
        parser.add_argument(
            "count",
            nargs="?",
            type=int,
            default=5,
            help="Desired number of objects per provider (default is 5)",
        )

    def handle(self, *args, **options):
        count = options["count"]
        self.stdout.write(self.style.NOTICE(f"Ensuring {count} objects per Faker provider..."))

        result = create_data(count)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done! Created {result['object_types']} object types, "
                f"{result['attributes']} attributes, "
                f"{result['objects']} objects, "
                f"{result['values']} values."
            )
        )
