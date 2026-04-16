## Review: `django_graphene_filters/orderset.py`

### High: PostgreSQL `*_DISTINCT` can fail outright on annotated querysets

[`AdvancedOrderSet.apply_distinct`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py#L143) routes PostgreSQL to [`_apply_distinct_postgres`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py#L161), which ends with:

```python
if full_order:
    queryset = queryset.order_by(*full_order)
return queryset.distinct(*distinct_fields)
```

That is fine only for plain querysets. In this library, though, the incoming queryset can already be annotated before ordering runs, especially through the PostgreSQL search filters in [`filters.py`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/filters.py). Django does not support `annotate()` combined with `distinct(*fields)` on PostgreSQL, so a query that mixes search/annotated filtering with `ASC_DISTINCT` / `DESC_DISTINCT` will raise at runtime instead of returning results.

This is a real integration bug in the current pipeline, because ordering is applied after filtering in [`connection_field.py`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/connection_field.py#L333). The PostgreSQL path needs to detect existing annotations and fall back to the window-function implementation, or otherwise wrap/restructure the query.

---

### Medium: `RelatedOrder` declarations are not inherited by subclasses

[`OrderSetMetaclass.__new__`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py#L17) builds `related_orders` from `attrs.items()` only:

```python
new_class.related_orders = OrderedDict(
    [(n, f) for n, f in attrs.items() if isinstance(f, orders.BaseRelatedOrder)]
)
```

That means a subclass loses every `RelatedOrder` declared on its base class unless it redeclares them manually. The breakage is broader than just metadata:

- [`get_fields`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py#L230) no longer exposes inherited related fields to the schema builder.
- [`get_flat_orders`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py#L86) no longer recognizes those inherited relation names during flattening.
- [`check_permissions`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py#L57) no longer delegates permission checks through them.

So subclassing an `AdvancedOrderSet` silently strips inherited relationship ordering support. The metaclass should merge base classes' `related_orders` the same way the filter side relies on inherited declarations.

---

### What looks solid

- [`_apply_distinct_postgres`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py#L161) correctly deduplicates contradictory `ORDER BY` entries for the same distinct field.
- [`get_flat_orders`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/orderset.py#L86) handles nested related traversal and `*_DISTINCT` extraction cleanly.
- Permission delegation for related order paths is wired consistently with the filter side.

**Summary:** the main runtime risk is PostgreSQL `distinct(*fields)` on an already-annotated queryset. The main API/design risk is that inherited `RelatedOrder` declarations disappear in subclasses.
