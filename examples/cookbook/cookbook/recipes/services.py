"""Dynamic data seeding service using Faker providers.

Discovers ALL Faker providers and their generator methods at runtime.
No hardcoded provider names or method lists — fully dynamic.

Quick check — print the number of detected providers and methods:

    uv run python -c "
    import django, os
    os.environ['DJANGO_SETTINGS_MODULE'] = 'cookbook.settings'
    django.setup()
    from cookbook.recipes.services import discover_providers
    from faker import Faker
    p = discover_providers(Faker())
    print(f'{len(p)} providers, {sum(len(m) for m in p.values())} methods')
    "

Expected output (Faker 37.1.0): 24 providers, 171 methods

Estimating created rows for a given count (X):

    ObjectType  = 24              (one per provider)
    Attribute   = 171             (one per method)
    Object      = 24 * X         (X objects per provider)
    Value       = 171 * X        (one value per attribute per object)
    ---
    Total rows  = 24 + 171 + (24 * X) + (171 * X)
                = 195 + 195X

    Examples:
        X=1   ->   390 rows
        X=5   ->  1170 rows
        X=50  -> 9945 rows
"""

import inspect
import pkgutil
import random
from collections.abc import Callable

from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from faker import Faker
from faker.providers import BaseProvider


def _is_safe_generator(fake: Faker, method_name: str) -> bool:
    """Probe a Faker method by calling it once to check it returns a usable string value.

    Rejects methods that return non-scalar types (bytes, dicts, lists, tuples, etc.)
    or raise exceptions when called with no arguments.
    """
    try:
        result = getattr(fake, method_name)()
    except Exception:
        return False

    # Only accept simple scalar types that can be meaningfully stored as text
    return isinstance(result, (str, int, float, bool))


def discover_providers(fake: Faker) -> dict[str, list[str]]:
    """Discover all Faker providers and their no-arg generator methods.

    Returns a dict mapping provider short names to lists of callable method names.
    Each method is probed at runtime to confirm it returns a usable scalar value.
    Nothing is hardcoded — the result is entirely driven by introspecting Faker.
    """
    import faker.providers as fp

    base_methods = set(dir(BaseProvider))

    providers: dict[str, list[str]] = {}

    for _importer, modname, ispkg in pkgutil.walk_packages(fp.__path__, fp.__name__ + "."):
        if not ispkg:
            continue

        short_name = modname.replace("faker.providers.", "")

        # Only use top-level providers (skip locale sub-packages like "address.en_US")
        if "." in short_name:
            continue

        try:
            mod = __import__(modname, fromlist=["Provider"])
        except ImportError:
            continue

        if not hasattr(mod, "Provider"):
            continue

        provider_cls = mod.Provider
        methods: list[str] = []

        for name in sorted(dir(provider_cls)):
            if name.startswith("_") or name in base_methods:
                continue

            attr = getattr(provider_cls, name, None)
            if attr is None or not callable(attr) or isinstance(attr, property):
                continue

            # Only include methods with no required args beyond self
            try:
                sig = inspect.signature(attr)
                params = list(sig.parameters.values())
                required = [
                    p
                    for p in params[1:]  # skip self
                    if p.default is inspect.Parameter.empty
                    and p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                ]
                if len(required) != 0:
                    continue
            except (ValueError, TypeError):
                continue

            # Probe the method to verify it returns a usable scalar
            if _is_safe_generator(fake, name):
                methods.append(name)

        if methods:
            providers[short_name] = methods

    return providers


def _fake_value(fake: Faker, method_name: str) -> str:
    """Call a Faker method and return its result as a string."""
    fn: Callable = getattr(fake, method_name)
    result = fn()
    return str(result)


def seed_data(count: int) -> dict[str, int]:
    """Seed the database with Faker-driven data for every discovered provider.

    Ensures at least ``count`` ``Object`` instances exist per provider.
    Only creates the difference if some already exist.

    For each provider (e.g. "bank", "person", "address"):
      - Creates one ``ObjectType`` (or reuses existing)
      - Creates one ``Attribute`` per provider method (or reuses existing)
      - Ensures ``count`` ``Object`` instances exist (creates only the shortfall)
      - Each new ``Object`` gets one ``Value`` per ``Attribute``

    ``is_private`` is randomly set on every created model instance (~50/50).

    Returns a summary dict with counts of newly created rows.
    """
    fake = Faker()
    providers = discover_providers(fake)

    total_object_types = 0
    total_attributes = 0
    total_objects = 0
    total_values = 0

    for provider_name, method_names in sorted(providers.items()):
        # --- ObjectType ---
        obj_type, created = ObjectType.objects.get_or_create(
            name=provider_name,
            defaults={
                "description": f"Auto-generated from Faker's {provider_name} provider",
                "is_private": random.choice([True, False]),
            },
        )
        if created:
            total_object_types += 1

        # --- Attributes (one per method) ---
        attrs: list[Attribute] = []
        for method_name in method_names:
            attr, created = Attribute.objects.get_or_create(
                name=method_name,
                object_type=obj_type,
                defaults={
                    "description": f"{provider_name}.{method_name}",
                    "is_private": random.choice([True, False]),
                },
            )
            attrs.append(attr)
            if created:
                total_attributes += 1

        # --- Objects + Values (only create the shortfall) ---
        existing_count = Object.objects.filter(object_type=obj_type).count()
        needed = max(0, count - existing_count)

        for _ in range(needed):
            obj = Object.objects.create(
                name=f"{provider_name}_{fake.uuid4()[:8]}",
                description=f"Generated {provider_name} instance",
                object_type=obj_type,
                is_private=random.choice([True, False]),
            )
            total_objects += 1

            values_to_create = [
                Value(
                    value=_fake_value(fake, attr.name),
                    description="",
                    attribute=attr,
                    object=obj,
                    is_private=random.choice([True, False]),
                )
                for attr in attrs
            ]
            Value.objects.bulk_create(values_to_create)
            total_values += len(values_to_create)

    return {
        "object_types": total_object_types,
        "attributes": total_attributes,
        "objects": total_objects,
        "values": total_values,
    }


# --------------------------------------------------------------------------- #
# User seeding
# --------------------------------------------------------------------------- #

# The four model-level view permissions used by schema.py get_queryset branches.
VIEW_PERMISSIONS = [
    "view_objecttype",
    "view_object",
    "view_attribute",
    "view_value",
]

# Shared password for all test users — makes manual login easy.
TEST_USER_PASSWORD = "admin"


def create_users(count: int = 1) -> dict[str, int]:
    """Create test users with individual model-view permissions.

    For each unit in ``count``, creates one user per view permission
    (4 users per unit).  Each user receives **only** the single
    permission matching their role so the schema's ``get_queryset``
    branches can be exercised independently.

    Naming: ``<permission>_<n>`` (e.g. ``view_object_1``,
    ``view_attribute_2``).  All users share the password
    ``TEST_USER_PASSWORD`` and are **not** staff.

    Also creates one ``staff_<n>`` superuser per unit for convenience.

    The function is idempotent — existing usernames are skipped.

    Returns a summary dict with the number of newly created users.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission

    User = get_user_model()
    created = 0

    fake = Faker()

    for n in range(1, count + 1):
        last_name = fake.last_name()

        # --- Staff user ---
        username = f"staff_{n}"
        if not User.objects.filter(username=username).exists():
            User.objects.create_user(
                username=username,
                password=TEST_USER_PASSWORD,
                is_staff=True,
                first_name="Staff",
                last_name=last_name,
            )
            created += 1

        # --- Regular user (no permissions, not staff) ---
        username = f"regular_{n}"
        if not User.objects.filter(username=username).exists():
            User.objects.create_user(
                username=username,
                password=TEST_USER_PASSWORD,
                is_staff=False,
                first_name="Regular",
                last_name=last_name,
            )
            created += 1

        # --- Per-permission users ---
        for perm_codename in VIEW_PERMISSIONS:
            username = f"{perm_codename}_{n}"
            if not User.objects.filter(username=username).exists():
                # e.g. "view_object" -> "View Object"
                first_name = perm_codename.replace("_", " ").title()
                user = User.objects.create_user(
                    username=username,
                    password=TEST_USER_PASSWORD,
                    is_staff=False,
                    first_name=first_name,
                    last_name=last_name,
                )
                perm = Permission.objects.get(
                    codename=perm_codename,
                    content_type__app_label="recipes",
                )
                user.user_permissions.add(perm)
                created += 1

    return {"users": created}


def delete_users(target: int | str) -> dict[str, int]:
    """Delete test users created by ``create_users``.

    Superusers (``is_superuser=True``) are **never** deleted.

    Modes:
      - ``target`` is an **int**: delete the first *target* non-superusers
        (by primary key order).
      - ``target == "all"``: delete every non-superuser.

    Returns a summary dict with counts of deleted users.
    """
    from django.contrib.auth import get_user_model

    User = get_user_model()
    result: dict[str, int] = {"users": 0}

    if target == "all":
        qs = User.objects.exclude(is_superuser=True)
        result["users"] = qs.count()
        qs.delete()
    else:
        count = int(target)
        qs = User.objects.exclude(is_superuser=True).order_by("pk")
        pks = list(qs.values_list("pk", flat=True)[:count])
        if pks:
            result["users"] = len(pks)
            User.objects.filter(pk__in=pks).delete()

    return result


def delete_data(target: int | str) -> dict[str, int]:
    """Delete data from the database.

    Modes:
      - ``target`` is an **int**: delete the first *target* ``Object`` rows
        (by primary key order). Related ``Value`` rows cascade automatically.
      - ``target == "all"``: delete every ``Object`` and ``Value``.
      - ``target == "everything"``: wipe all four tables
        (``Value``, ``Object``, ``Attribute``, ``ObjectType``).

    Returns a summary dict with counts of deleted rows per model.
    """
    result: dict[str, int] = {
        "object_types": 0,
        "attributes": 0,
        "objects": 0,
        "values": 0,
    }

    if target == "everything":
        result["values"] = Value.objects.all().count()
        result["objects"] = Object.objects.all().count()
        result["attributes"] = Attribute.objects.all().count()
        result["object_types"] = ObjectType.objects.all().count()
        # Delete in FK-safe order
        Value.objects.all().delete()
        Object.objects.all().delete()
        Attribute.objects.all().delete()
        ObjectType.objects.all().delete()

    elif target == "all":
        result["values"] = Value.objects.all().count()
        result["objects"] = Object.objects.all().count()
        Value.objects.all().delete()
        Object.objects.all().delete()

    else:
        count = int(target)
        pks = list(Object.objects.order_by("pk").values_list("pk", flat=True)[:count])
        if pks:
            result["values"] = Value.objects.filter(object__pk__in=pks).count()
            Value.objects.filter(object__pk__in=pks).delete()
            result["objects"] = Object.objects.filter(pk__in=pks).count()
            Object.objects.filter(pk__in=pks).delete()

    return result
