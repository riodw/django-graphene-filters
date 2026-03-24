from cookbook.recipes.models import Attribute, Object, ObjectType, Value
from cookbook.recipes.services import create_users, delete_data, delete_users, seed_data
from django.contrib import admin, messages
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.shortcuts import redirect

User = get_user_model()


# --- Custom UserAdmin with create_users / delete_users via query params ---
admin.site.unregister(User)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("id", "username", "first_name", "last_name", "is_staff", "is_superuser")
    list_display_links = ("id", "username")
    list_filter = ("is_staff", "is_superuser", "is_active", "user_permissions")

    def changelist_view(self, request, extra_context=None):
        # --- create_users ---
        create_count = request.GET.get("create_users")
        if create_count:
            try:
                count = int(create_count)
                if count > 0:
                    result = create_users(count)
                    self.message_user(
                        request,
                        f"Created {result['users']} test users.",
                        messages.SUCCESS,
                    )
                new_get = request.GET.copy()
                new_get.pop("create_users")
                return redirect(f"{request.path}?{new_get.urlencode()}")
            except (ValueError, TypeError):
                self.message_user(
                    request,
                    "Invalid value for create_users. Must be an integer.",
                    messages.ERROR,
                )

        # --- delete_users ---
        delete_target = request.GET.get("delete_users")
        if delete_target:
            try:
                result = delete_users(delete_target)
                self.message_user(
                    request,
                    f"Deleted {result['users']} users." if result["users"] else "Nothing to delete.",
                    messages.SUCCESS if result["users"] else messages.WARNING,
                )
                new_get = request.GET.copy()
                new_get.pop("delete_users")
                return redirect(f"{request.path}?{new_get.urlencode()}")
            except (ValueError, TypeError):
                self.message_user(
                    request,
                    'Invalid value for delete_users. Use an integer or "all".',
                    messages.ERROR,
                )

        return super().changelist_view(request, extra_context=extra_context)


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
        # --- seed_data ---
        seed_count = request.GET.get("seed_data")
        if seed_count:
            try:
                count = int(seed_count)
                if count > 0:
                    result = seed_data(count)
                    self.message_user(
                        request,
                        f"Created {result['object_types']} object types, "
                        f"{result['attributes']} attributes, "
                        f"{result['objects']} objects, "
                        f"{result['values']} values.",
                        messages.SUCCESS,
                    )
                new_get = request.GET.copy()
                new_get.pop("seed_data")
                return redirect(f"{request.path}?{new_get.urlencode()}")
            except (ValueError, TypeError):
                self.message_user(
                    request,
                    "Invalid value for seed_data. Must be an integer.",
                    messages.ERROR,
                )

        # --- delete_data ---
        delete_target = request.GET.get("delete_data")
        if delete_target:
            try:
                result = delete_data(delete_target)
                parts = []
                if result["object_types"]:
                    parts.append(f"{result['object_types']} object types")
                if result["attributes"]:
                    parts.append(f"{result['attributes']} attributes")
                if result["objects"]:
                    parts.append(f"{result['objects']} objects")
                if result["values"]:
                    parts.append(f"{result['values']} values")
                summary = ", ".join(parts) if parts else "nothing"
                self.message_user(request, f"Deleted {summary}.", messages.SUCCESS)
                new_get = request.GET.copy()
                new_get.pop("delete_data")
                return redirect(f"{request.path}?{new_get.urlencode()}")
            except (ValueError, TypeError):
                self.message_user(
                    request,
                    'Invalid value for delete_data. Use an integer, "all", or "everything".',
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
