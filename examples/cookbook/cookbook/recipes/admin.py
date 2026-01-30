from django.contrib import admin

from cookbook.recipes.models import Attribute, Object, ObjectType, Value


admin.site.register(ObjectType)
admin.site.register(Object)
admin.site.register(Attribute)
admin.site.register(Value)
