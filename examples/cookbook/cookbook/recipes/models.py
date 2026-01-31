from django.db import models


class ObjectType(models.Model):
    name = models.TextField()
    description = models.TextField(
        blank=True,
        default="",
    )
    # history
    created_date = models.DateTimeField(
        auto_now_add=True,
        editable=False,
    )
    updated_date = models.DateTimeField(
        auto_now=True,
        editable=False,
    )

    class Meta:
        verbose_name = "Object Type"
        verbose_name_plural = "Object Types"

    def __str__(self):
        return self.name


class Object(models.Model):
    name = models.TextField()
    description = models.TextField(
        blank=True,
        default="",
    )
    # FK's
    object_type = models.ForeignKey(
        ObjectType,
        related_name="objectss",
        on_delete=models.CASCADE,
    )
    # parent = models.ForeignKey(
    #     "self",
    #     on_delete=models.CASCADE,
    #     null=True,
    #     blank=True,
    # )
    # history
    created_date = models.DateTimeField(
        auto_now_add=True,
        editable=False,
    )
    updated_date = models.DateTimeField(
        auto_now=True,
        editable=False,
    )

    class Meta:
        verbose_name = "Object"
        verbose_name_plural = "Objects"

    def __str__(self):
        return self.name


class Attribute(models.Model):
    name = models.TextField()
    description = models.TextField(
        blank=True,
        default="",
    )
    # FK's
    object_type = models.ForeignKey(
        ObjectType,
        related_name="attributes",
        on_delete=models.CASCADE,
    )
    # history
    created_date = models.DateTimeField(
        auto_now_add=True,
        editable=False,
    )
    updated_date = models.DateTimeField(
        auto_now=True,
        editable=False,
    )

    class Meta:
        verbose_name = "Attribute"
        verbose_name_plural = "Attributes"

    def __str__(self):
        return self.name


class Value(models.Model):
    value = models.TextField()
    description = models.TextField(
        blank=True,
        default="",
    )
    # FK's
    attribute = models.ForeignKey(
        Attribute,
        related_name="values",
        on_delete=models.CASCADE,
    )
    object = models.ForeignKey(
        Object,
        related_name="values",
        on_delete=models.CASCADE,
    )
    # history
    created_date = models.DateTimeField(
        auto_now_add=True,
        editable=False,
    )
    updated_date = models.DateTimeField(
        auto_now=True,
        editable=False,
    )

    class Meta:
        verbose_name = "Value"
        verbose_name_plural = "Values"

    def __str__(self):
        return self.value
