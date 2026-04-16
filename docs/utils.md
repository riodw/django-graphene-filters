## Review: `django_graphene_filters/utils.py`

### Medium: Bare transform lookups are omitted from `__all__` filter generation

[`lookups_for_field`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/utils.py#L24) treats every `Transform` as something that must be followed by another lookup:

```python
for expr, lookup in model_field.get_lookups().items():
    if issubclass(lookup, Transform):
        transform = lookup(Expression(model_field))
        lookups += [LOOKUP_SEP.join([expr, sub_expr]) for sub_expr in lookups_for_transform(transform)]
    else:
        lookups.append(expr)
```

That means a valid terminal transform like `created__date` is never returned; only `created__date__exact`, `created__date__lt`, and so on are generated. The same omission applies recursively in [`lookups_for_transform`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/utils.py#L45), so nested transform chains also lose their implicit-`exact` form.

This matters because [`AdvancedFilterSet._get_fields`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/filterset.py#L800) uses `lookups_for_field()` when a field is declared as `"__all__"`. So the schema silently fails to expose a class of valid ORM filters whenever transform lookups are auto-expanded.

---

### Medium: Lookup discovery ignores lookups registered on the transform itself

[`lookups_for_transform`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/utils.py#L63) walks `transform.output_field.get_lookups()`:

```python
for expr, lookup in transform.output_field.get_lookups().items():
```

That bypasses Django's normal lookup resolution on the transform object/class and only inspects the output field's registered lookups. If a custom transform defines or registers lookups on the transform class itself, those valid lookup expressions are omitted from discovery.

In practice that means `Meta.fields = {"name": "__all__"}` can under-generate filters for third-party or project-specific transforms even though the ORM would accept them.

---

### What looks solid

- The direct self-recursion guard in [`lookups_for_transform`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/utils.py#L65) does prevent the obvious infinite-loop case.
- The functions are narrowly scoped and the call site in [`filterset.py`](/Users/riordenweber/projects/django-graphene-filters/django_graphene_filters/filterset.py#L800) is easy to reason about.

**Summary:** the main risk is incomplete lookup discovery. Today the utility under-reports valid transform-based filters, which in turn means `"__all__"` filter generation can silently miss schema fields that Django itself would support.
