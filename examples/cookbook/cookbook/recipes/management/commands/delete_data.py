from cookbook.recipes.services import delete_data
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Delete data from the database. "
        "Pass an integer to delete the first N objects, "
        '"all" to delete all objects and values, '
        'or "everything" to wipe all four tables.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "target",
            type=str,
            help='Number of objects to delete, "all", or "everything"',
        )

    def handle(self, *args, **options):
        target = options["target"]

        # Validate: must be a positive int, "all", or "everything"
        if target not in ("all", "everything"):
            try:
                count = int(target)
                if count < 1:
                    self.stderr.write(self.style.ERROR("Count must be a positive integer."))
                    return
            except ValueError:
                self.stderr.write(
                    self.style.ERROR(
                        f'Invalid target "{target}". Use a positive integer, "all", or "everything".'
                    )
                )
                return

        self.stdout.write(self.style.NOTICE(f"Deleting data (target={target})..."))

        result = delete_data(target)

        parts = []
        if result["object_types"]:
            parts.append(f"{result['object_types']} object types")
        if result["attributes"]:
            parts.append(f"{result['attributes']} attributes")
        if result["objects"]:
            parts.append(f"{result['objects']} objects")
        if result["values"]:
            parts.append(f"{result['values']} values")

        if parts:
            self.stdout.write(self.style.SUCCESS(f"Deleted {', '.join(parts)}."))
        else:
            self.stdout.write(self.style.WARNING("Nothing to delete."))
