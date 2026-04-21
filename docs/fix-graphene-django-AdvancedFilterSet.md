# Upstream fix brief: `GlobalIDFilter` + `in`/`range` lookup produces cryptic error

**Target repo:** [graphql-python/graphene-django](https://github.com/graphql-python/graphene-django)
**Status:** Draft — keep as internal reference until we open an issue + PR.
**Written against:** graphene-django `main` branch at the time of `django-graphene-filters` 1.0.0.

## TL;DR

When a `FilterSet` inheriting `GrapheneFilterSetMixin` declares a `ForeignKey`
(or `OneToOneField` / `AutoField`) with the `in` or `range` lookup via
`Meta.fields`, graphene-django pairs the singular `GlobalIDFilter` with a
multi-valued lookup. The filter's `field_class` (`GlobalIDFormField`) is not
list-aware, so the first request into that filter raises a cryptic
`TypeError` from Python's `base64` machinery rather than a schema-level
diagnostic:

```
TypeError: argument should be a bytes-like object or ASCII string, not 'list'
```

This brief covers the repro, root cause, proposed fix, and test plan.

## Reproduction

### Minimal GraphQL schema

```python
import django_filters
from django.db import models
from graphene_django.filter.filterset import GrapheneFilterSetMixin


class Role(models.Model):
    name = models.CharField(max_length=32)


class UserRole(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE)


class UserRoleFilter(GrapheneFilterSetMixin, django_filters.FilterSet):
    class Meta:
        model = UserRole
        fields = {"role": ["in"]}       # <-- the problematic declaration
```

### Request that blows up

```graphql
query {
  allUserRoles(role_In: ["<base64-global-id-1>", "<base64-global-id-2>"]) {
    edges { node { id } }
  }
}
```

### Traceback (abridged)

```
File ".../graphene_django/filter/filters.py", line <NN>, in to_python
    _type, _id = from_global_id(value)
File ".../graphql_relay/node/node.py", line <NN>, in from_global_id
    return tuple(unbase64(global_id).split(":", 1))
File ".../graphql_relay/utils/base64.py", line <NN>, in unbase64
    return b64decode(b).decode("utf-8")
TypeError: argument should be a bytes-like object or ASCII string, not 'list'
```

## Root cause

graphene-django's filter overrides map **all** `ForeignKey`-family fields to
a single-value filter class, regardless of the requested lookup expression:

```python
# graphene_django/filter/filterset.py
GRAPHENE_FILTER_SET_OVERRIDES = {
    models.AutoField:       {"filter_class": GlobalIDFilter},              # singular
    models.OneToOneField:   {"filter_class": GlobalIDFilter},              # singular
    models.ForeignKey:      {"filter_class": GlobalIDFilter},              # singular
    models.ManyToManyField: {"filter_class": GlobalIDMultipleChoiceFilter},# plural
    models.ManyToOneRel:    {"filter_class": GlobalIDMultipleChoiceFilter},# plural
    models.ManyToManyRel:   {"filter_class": GlobalIDMultipleChoiceFilter},# plural
}
```

`GlobalIDFilter.field_class == GlobalIDFormField`, which expects a single
string and calls `from_global_id(value)` on it unconditionally. When
django-filter's `FilterSet` sees `lookup_expr="in"`, it does **not**
auto-promote the filter to a list-handling variant in the graphene case — so
the singular filter receives a list.

For bare scalar fields (`CharField`, `IntegerField`, …) django-filter wraps
the default filter class in `InFilter` / `RangeFilter` automatically. For the
graphene overrides this wrapping never happens because
`GRAPHENE_FILTER_SET_OVERRIDES` replaces the filter class wholesale.

## Proposed fix

Teach `GrapheneFilterSetMixin` (or the `filter_for_lookup` path) to swap
`GlobalIDFilter` for `GlobalIDMultipleChoiceFilter` when the requested lookup
is `in` or `range`. This mirrors the existing M2M behaviour and what
django-filter already does for scalar fields.

### Option A — override `filter_for_lookup`

Smallest surgical change; lives on the mixin:

```python
# graphene_django/filter/filterset.py
from django.db import models

_MULTI_LOOKUPS = ("in", "range")


class GrapheneFilterSetMixin(BaseFilterSet):
    FILTER_DEFAULTS = dict(
        itertools.chain(
            FILTER_FOR_DBFIELD_DEFAULTS.items(),
            GRAPHENE_FILTER_SET_OVERRIDES.items(),
        )
    )

    @classmethod
    def filter_for_lookup(cls, field, lookup_type):
        filter_class, params = super().filter_for_lookup(field, lookup_type)
        if (
            lookup_type in _MULTI_LOOKUPS
            and filter_class is GlobalIDFilter
            and isinstance(field, (models.AutoField, models.OneToOneField, models.ForeignKey))
        ):
            return GlobalIDMultipleChoiceFilter, params
        return filter_class, params
```

- Keeps the `GRAPHENE_FILTER_SET_OVERRIDES` dict unchanged.
- Behaviour only changes for lookups that were already broken.
- Does not affect users who explicitly declare a filter on a FK.

### Option B — widen the overrides dict

Less surgical but more declarative. Change the values in
`GRAPHENE_FILTER_SET_OVERRIDES` for FK / O2O / AutoField into a shape that
encodes the per-lookup filter class. django-filter's `FILTER_DEFAULTS` already
supports this shape for scalar types via `filter_class` plus an `extra` / helper.

Prefer **Option A** unless a maintainer asks for B — the surface area is
smaller and the diff reads as "fix a cryptic error", not "re-architect the
override table".

## Suggested test

Add to `graphene_django/filter/tests/test_fields.py` (or the equivalent
current module):

```python
def test_foreign_key_in_lookup_accepts_list_of_global_ids(db):
    """Regression test: FK + `in` should accept a list of Relay global IDs.

    Previously the combination raised ``TypeError: argument should be a
    bytes-like object or ASCII string, not 'list'`` because
    ``GlobalIDFilter`` was paired with a multi-valued lookup despite being a
    single-value filter class.
    """
    from graphql_relay import to_global_id

    role_a = Role.objects.create(name="a")
    role_b = Role.objects.create(name="b")
    UserRole.objects.create(role=role_a)
    UserRole.objects.create(role=role_b)

    gid_a = to_global_id("RoleType", role_a.pk)
    gid_b = to_global_id("RoleType", role_b.pk)

    query = f'''
        query {{
          allUserRoles(role_In: ["{gid_a}", "{gid_b}"]) {{
            edges {{ node {{ id }} }}
          }}
        }}
    '''
    result = schema.execute(query)
    assert result.errors is None
    assert len(result.data["allUserRoles"]["edges"]) == 2
```

A symmetric test for `range` is nice-to-have but not load-bearing — `range`
on a FK is unusual in practice.

## Error-message improvement (bonus)

Even if Option A is accepted, a one-line improvement to `GlobalIDFormField`
gives future users a clear diagnostic when they hit the same mismatch via
a different path (e.g. explicit filter declaration):

```python
# graphene_django/forms/fields.py
class GlobalIDFormField(forms.CharField):
    def to_python(self, value):
        if isinstance(value, (list, tuple)):
            raise forms.ValidationError(
                "GlobalIDFormField received a list; use GlobalIDMultipleChoiceFilter "
                "for multi-value lookups (in / range)."
            )
        ...
```

Optional — ship the behaviour fix first, the message fix can ride a follow-up.

## Downstream impact

`django-graphene-filters` added `GrapheneFilterSetMixin` to
`AdvancedFilterSet` as part of its 1.0.0 class-based-naming work
(see `docs/spec-base_type_naming.md`). That change makes nested
`RelatedFilter` traversals go through the graphene overrides just like the
top-level, unifying the schema — and surfacing this bug at the nested level
where it used to be masked. The library ships a documented workaround
(filter via a scalar child rather than FK `in`), but an upstream fix would
let downstream consumers drop the caveat.

## Open questions for the maintainers

1. Is Option A acceptable, or do they prefer reworking the overrides dict
   into a shape that expresses per-lookup filter classes?
2. Should the multi-value promotion apply to any filter class whose
   `field_class` is a subclass of `CharField` / single-value field, or stay
   narrowly scoped to `GlobalIDFilter`?
3. Is there appetite for a clearer error message on `GlobalIDFormField`
   regardless of whether the promotion ships?

## Rollout plan (us, not them)

1. Open an issue with the reproduction above; tag it `bug` + `filter`.
2. If maintainers confirm interest, open a PR implementing Option A +
   regression test.
3. Independently of upstream acceptance, keep the workaround in
   `django-graphene-filters` — don't block our 1.0.0 on their merge.

## File checklist when opening the PR

- `graphene_django/filter/filterset.py` — `filter_for_lookup` override.
- `graphene_django/filter/tests/test_fields.py` — regression test.
- `CHANGELOG.md` — one-line entry under "Bug fixes".
- `docs/filtering.rst` (or whichever filter doc exists) — note that `in` /
  `range` on FK / O2O now works out of the box.
