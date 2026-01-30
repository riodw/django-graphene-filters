import factory
from cookbook.recipes.models import Attribute, Object, ObjectType, Value


class ObjectTypeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ObjectType

    name = factory.Faker("word")
    description = factory.Faker("sentence")


class AttributeFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Attribute

    name = factory.Faker("word")
    description = factory.Faker("sentence")
    object_type = factory.SubFactory(ObjectTypeFactory)


class ObjectFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Object

    name = factory.Faker("word")
    description = factory.Faker("sentence")
    object_type = factory.SubFactory(ObjectTypeFactory)


class ValueFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Value

    value = factory.Faker("word")
    description = factory.Faker("sentence")
    attribute = factory.SubFactory(AttributeFactory)
    object = factory.SubFactory(ObjectFactory)
