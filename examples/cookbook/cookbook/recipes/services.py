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


def create_data(count: int) -> dict[str, int]:
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
