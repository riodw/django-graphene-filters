"""`AdvancedOrderSet` class module."""

import enum
from collections import OrderedDict
from collections.abc import Mapping
from graphene.utils.str_converters import to_snake_case
from . import orders

class OrderSetMetaclass(type):
    """Custom metaclass for creating OrderSet classes and attaching RelatedOrders."""

    def __new__(cls, name, bases, attrs):
        new_class = super().__new__(cls, name, bases, attrs)
        new_class.related_orders = OrderedDict(
            [(n, f) for n, f in attrs.items() if isinstance(f, orders.BaseRelatedOrder)]
        )
        for f in new_class.related_orders.values():
            f.bind_orderset(new_class)
        return new_class


class AdvancedOrderSet(metaclass=OrderSetMetaclass):
    """Base class for generating and applying advanced relationship sorting, complete with permission checks."""

    def __init__(self, data=None, queryset=None, request=None):
        self.data = data or []
        self.qs = queryset
        self.request = request

        if self.data and self.qs is not None:
            # Flatten the GraphQL nested InputObjectType array into Django __ paths
            flat_orders = self.get_flat_orders(self.data)
            
            # Hook validation (so you can reject before applying)
            self.check_permissions(self.request, flat_orders)
            
            # Apply to QuerySet
            self.qs = self.qs.order_by(*flat_orders)

    def check_permissions(self, request, requested_orderings):
        """Validate whether the user is allowed to order by these fields.
        
        It looks for strictly matching methods on the orderset prefixed by `check_` and `_permission`.
        E.g. for `category__name`, it searches for `check_category_name_permission(request)`.
        If the user lacks permission, you can raise an error or drop the field.

        For related paths (e.g. `object_type__name`), the check is also delegated
        to the child orderset so that permission methods defined there are honoured.
        """
        for order_path in requested_orderings:
            # Remove leading `-`
            clean_path = order_path.lstrip('-')
            method_name = f"check_{clean_path.replace('__', '_')}_permission"
            
            if hasattr(self, method_name):
                getattr(self, method_name)(request)

            # Delegate to the child orderset that owns the remainder of the path
            for rel_order in getattr(self.__class__, "related_orders", {}).values():
                prefix = f"{rel_order.field_name}__"
                if clean_path.startswith(prefix):
                    remainder = clean_path[len(prefix):]
                    target_class = rel_order.orderset
                    if target_class:
                        child = object.__new__(target_class)
                        child.check_permissions(request, [remainder])
                    break

    @classmethod
    def get_flat_orders(cls, order_data, prefix=""):
        """Recursively parses nested order dictionaries downwards."""
        flat_orders = []
        for order_item in order_data:
            if isinstance(order_item, Mapping):
                # An item generally possesses exactly one key -> value representing one hop
                for key, value in order_item.items():
                    snake_key = to_snake_case(key)
                    related_orders = getattr(cls, "related_orders", {})
                    
                    if snake_key in related_orders:
                        # Fetch correct model field_name incase it diverges from GraphQL alias
                        real_field_name = related_orders[snake_key].field_name
                        current_prefix = f"{prefix}{real_field_name}__" if prefix else f"{real_field_name}__"
                        
                        target_orderset = related_orders[snake_key].orderset
                        if isinstance(value, Mapping) and target_orderset:
                             # Recurse with prefix (e.g., 'category__')
                             flat_orders.extend(target_orderset.get_flat_orders([value], current_prefix))
                    else:
                        current_prefix = f"{prefix}{snake_key}__" if prefix else f"{snake_key}__"
                        
                        if isinstance(value, Mapping):
                             # Native field recurse if any, although leaf nodes generally shouldn't be objects 
                             flat_orders.extend(cls.get_flat_orders([value], current_prefix))
                        else:
                             # Reached the leaf node -> direction is attached here
                             direction_str = value.value if isinstance(value, enum.Enum) else str(value)
                             direction = "-" if direction_str.lower() == "desc" else ""
                             field_path = current_prefix.rstrip("__") 
                             flat_orders.append(f"{direction}{field_path}")
        return flat_orders

    @classmethod
    def get_fields(cls):
        """Fetches flat order fields from the Meta definitions merging with explicit Relationships."""
        fields = OrderedDict()
        if hasattr(cls, "Meta") and hasattr(cls.Meta, "fields"):
            meta_fields = cls.Meta.fields
            # It could be a list ["name", "description"] or a dict mapping lookups 
            if isinstance(meta_fields, dict):
                for k in meta_fields.keys():
                    fields[k] = None
            else:
                for k in meta_fields:
                    fields[k] = None
                    
        for k, v in getattr(cls, "related_orders", {}).items():
            fields[k] = v
            
        return fields
