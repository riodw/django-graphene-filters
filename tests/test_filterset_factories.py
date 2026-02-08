from django.db import models

from django_graphene_filters.filterset import AdvancedFilterSet
from django_graphene_filters.filterset_factories import get_filterset_class


class FactoryModel(models.Model):
    name = models.CharField(max_length=100)

    class Meta:
        app_label = "recipes"


def test_get_filterset_class_from_meta():
    # Case where filterset_class is None
    # Hit line 31
    fs_class = get_filterset_class(None, model=FactoryModel, fields=["name"])
    assert issubclass(fs_class, AdvancedFilterSet)
    assert fs_class._meta.model == FactoryModel


def test_get_filterset_class_provided():
    class MyFS(AdvancedFilterSet):
        class Meta:
            model = FactoryModel
            fields = ["name"]

    fs_class = get_filterset_class(MyFS)
    assert fs_class is not None
    # graphene-django's setup_filterset returns a new class usually or wraps it
    assert fs_class._meta.model == FactoryModel
