## Review: `django_graphene_filters/orders.py`

### Medium: `RelatedOrder` accepts kwargs that always crash at construction

`RelatedOrder.__init__` accepts arbitrary `**kwargs`, and `BaseRelatedOrder.__init__` does the same:

```python
class BaseRelatedOrder(LazyRelatedClassMixin):
    def __init__(self, orderset: str | type, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._orderset = orderset
```

But `BaseRelatedOrder` only inherits from `LazyRelatedClassMixin`, whose MRO ends at `object`. That means any keyword argument is forwarded into `object.__init__`, which raises `TypeError`.

So the public constructor implies this is valid:

```python
RelatedOrder(MyOrderSet, field_name="author", required=True)
```

but at runtime it fails immediately. The signature should either reject extra kwargs explicitly or consume supported options before calling `super()`.

---

### Low: Reused `RelatedOrder` instances stay bound to the first owner

`bind_orderset()` only sets `bound_orderset` once:

```python
def bind_orderset(self, orderset: type) -> None:
    if not hasattr(self, "bound_orderset"):
        self.bound_orderset = orderset
```

That is fine if each declarative `RelatedOrder(...)` instance is attached to exactly one `AdvancedOrderSet` class. If the same instance is reused across multiple owners, lazy string resolution will keep using the first owner as the fallback module context.

That creates fragile behavior for string references such as:

```python
related = RelatedOrder("ChildOrderSet", field_name="child")
```

If the object is later attached to another orderset class in a different module, resolution still uses the first module. The wrong class can be imported, or import resolution can fail unexpectedly.

The safer pattern is to clone declarative order objects per owning class, or to overwrite the binding when ownership changes.

---

### What looks solid

- `orderset` resolution is cached back onto `self._orderset`, so repeated lookups do not repeatedly import.
- `RelatedOrder` itself is intentionally minimal; the traversal logic lives in [`orderset.py`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py), which keeps this module focused.
- The lazy-resolution behavior matches the library’s broader `Related*` pattern.

---

**Summary:** The main issue is the misleading constructor signature: `RelatedOrder` appears extensible via kwargs, but any kwargs currently crash. The secondary risk is sticky owner binding, which only shows up when a `RelatedOrder` instance is reused across multiple orderset classes.
