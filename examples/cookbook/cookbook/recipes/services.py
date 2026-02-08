from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from faker import Faker


def create_people(count: int):
    """Creates X number of People objects with associated Email, Phone, and City values."""
    fake = Faker()

    # 1. Get or create ObjectType "People"
    people_type, _ = ObjectType.objects.get_or_create(
        name="People",
        defaults={"description": "Automatically generated people objects"},
    )

    # 2. Get or create Attributes
    email_attr, _ = Attribute.objects.get_or_create(
        name="Email",
        object_type=people_type,
    )
    phone_attr, _ = Attribute.objects.get_or_create(
        name="Phone",
        object_type=people_type,
    )
    city_attr, _ = Attribute.objects.get_or_create(
        name="City",
        object_type=people_type,
    )

    # 3. Create X People
    created_count = 0
    for _ in range(count):
        person = Object.objects.create(
            name=fake.first_name(),
            description=fake.last_name(),
            object_type=people_type,
        )
        # Create 3 values per person
        Value.objects.create(
            value=fake.email(),
            description="",
            attribute=email_attr,
            object=person,
        )
        Value.objects.create(
            value=fake.phone_number(),
            description="",
            attribute=phone_attr,
            object=person,
        )
        Value.objects.create(
            value=fake.city(),
            description="",
            attribute=city_attr,
            object=person,
        )
        created_count += 1

    return created_count
