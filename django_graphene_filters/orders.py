"""Additional ordering classes for traversing relationships."""

from django.db.models import QuerySet

from .mixins import LazyRelatedClassMixin


class BaseRelatedOrder(LazyRelatedClassMixin):
    """Base class for related ordering. Serves as foundation for relationship sorting."""

    def __init__(self, orderset, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._orderset = orderset

    def bind_orderset(self, orderset) -> None:
        """Bind an orderset class to the current order instance."""
        if not hasattr(self, "bound_orderset"):
            self.bound_orderset = orderset

    @property
    def orderset(self):
        """Lazy-load the orderset class if it is specified as a string."""
        self._orderset = self.resolve_lazy_class(self._orderset, getattr(self, "bound_orderset", None))
        return self._orderset

    @orderset.setter
    def orderset(self, value) -> None:
        self._orderset = value


class RelatedOrder(BaseRelatedOrder):
    """A specialized ordering class for related models.

    This order allows for sorting across relationships by utilizing another OrderSet
    class defined for the related model.
    """

    def __init__(self, orderset, field_name: str, queryset: QuerySet | None = None, **kwargs) -> None:
        super().__init__(orderset, **kwargs)
        self.field_name = field_name
        self.queryset = queryset
