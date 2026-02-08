from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import create_people
from django.contrib import admin, messages
from django.shortcuts import redirect


class ObjectInline(admin.TabularInline):
    model = Object
    extra = 0
    show_change_link = True


class AttributeInline(admin.TabularInline):
    model = Attribute
    extra = 0
    show_change_link = True


@admin.register(ObjectType)
class ObjectTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "description", "created_date", "updated_date")
    search_fields = ("name", "description")
    inlines = [AttributeInline, ObjectInline]


class ValueInline(admin.TabularInline):
    model = Value
    extra = 1
    autocomplete_fields = ["attribute"]


@admin.register(Object)
class ObjectAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "description",
        "object_type",
        "created_date",
        "updated_date",
    )
    list_filter = ("object_type", "created_date")
    search_fields = ("name", "description")
    inlines = [ValueInline]
    autocomplete_fields = ["object_type"]

    def changelist_view(self, request, extra_context=None):
        create_count = request.GET.get("create_people")
        if create_count:
            try:
                count = int(create_count)
                if count > 0:
                    created_count = create_people(count)
                    self.message_user(
                        request,
                        f"Successfully created {created_count} people and {created_count * 3} associated values.",
                        messages.SUCCESS,
                    )
                # Redirect back to the same page without the create_people query param
                new_get = request.GET.copy()
                new_get.pop("create_people")
                return redirect(f"{request.path}?{new_get.urlencode()}")
            except (ValueError, TypeError):
                self.message_user(
                    request,
                    "Invalid value for create_people. Must be an integer.",
                    messages.ERROR,
                )
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(Attribute)
class AttributeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "description",
        "object_type",
        "created_date",
        "updated_date",
    )
    list_filter = ("object_type", "created_date")
    search_fields = ("name", "description")
    autocomplete_fields = ["object_type"]


@admin.register(Value)
class ValueAdmin(admin.ModelAdmin):
    list_display = (
        "value",
        "description",
        "attribute",
        "object",
        "created_date",
        "updated_date",
    )
    list_filter = (
        "attribute__object_type",
        "attribute",
        "created_date",
    )
    search_fields = ("value", "description", "object__name", "attribute__name")
    autocomplete_fields = ["attribute", "object"]
