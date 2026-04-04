## Review: `django_graphene_filters/filterset.py`

### High: Tree logic hardcodes `"and"`, `"or"`, `"not"` while the rest of the stack uses `settings`

`input_types` / `input_data_factories` use `settings.AND_KEY`, `settings.OR_KEY`, and `settings.NOT_KEY` (from `DJANGO_GRAPHENE_FILTERS`). `AdvancedFilterSet` still assumes literal keys:

```387:392:django_graphene_filters/filterset.py
            if key in ("and", "or"):
                ...
            elif key == "not":
```

```623:626:django_graphene_filters/filterset.py
            data={k: v for k, v in data.items() if k not in ("and", "or", "not")},
            and_forms=[self.create_form(form_class, and_data) for and_data in data.get("and", [])],
            or_forms=[self.create_form(form_class, or_data) for or_data in data.get("or", [])],
            not_form=(self.create_form(form_class, data["not"]) if data.get("not") else None),
```

`TreeFormMixin.errors` also hardcodes `"and"` / `"or"` / `"not"`.

If a project changes those keys in settings, GraphQL will emit the configured names, but **permission collection, form construction, and error aggregation will not see nested trees** → wrong or missing permission checks, empty `and_forms` / `or_forms` / `not_form`, and broken validation. This is an inconsistency bug, not theoretical.

---

### Medium: `find_filter` can return `None` but callers assume a filter

```629:645:django_graphene_filters/filterset.py
    def find_filter(self, data_key: str) -> Filter:
        ...
        for filter_value in self.filters.values():
            if filter_value.field_name == field_name and filter_value.lookup_expr == lookup_expr:
                return filter_value
```

There is no final `return None`, but execution can fall off the end → `None`. Then:

```661:662:django_graphene_filters/filterset.py
        for name, value in form.cleaned_data.items():
            qs, q = self.find_filter(name).filter(QuerySetProxy(qs, q), value)
```

Any `cleaned_data` key that does not resolve to a filter (unexpected key, rename drift, or a filter omitted from expansion) causes **`AttributeError: 'NoneType' object has no attribute 'filter'`**. The annotation `-> Filter` is also wrong unless you add an explicit `return None` / `raise` and handle it upstream.

---

### Medium: `expand_auto_filter` swallows all exceptions

```309:312:django_graphene_filters/filterset.py
        except Exception:
            # Swallow TypeError if field doesn't exist on model (e.g. reverse relation)
            ...
            pass
```

Any failure during auto-expansion (including real bugs) is silently ignored, so related `AutoFilter` expansion can fail **without a signal**, leaving filters missing until you notice at runtime.

---

### Low: Search splitting does not match the docstring

`build_search_conditions` says it handles “quoted and non-quoted” terms, but it only does `search_query.split()`:

```542:549:django_graphene_filters/filterset.py
        search_terms = search_query.split()
        ...
        for term in search_terms:
            term_conditions = reduce(operator.or_, (Q(**{lookup: term}) for lookup in orm_lookups))
            search_conditions &= term_conditions
```

So multiple terms are combined with **AND across terms** (each term must match at least one field), and there is **no quoted-phrase handling**. Either adjust the docstring or implement real tokenization.

---

### Low: `QuerySetProxy.__iter__`

```88:94:django_graphene_filters/filterset.py
    def __iter__(self) -> Iterator[Any]:
        ...
        return iter([self.__wrapped__, self.q])
```

Returning a two-item list is unusual for something proxying a `QuerySet`; anything that does `for x in proxy` gets the queryset and the `Q`, not rows. If this exists only for internal tests or a specific protocol, fine; otherwise it is surprising API surface.

---

### What looks solid

- Lazy `get_filters()` expansion with `_is_expanding_filters` and the careful `_expanded_filters` caching condition (`related_filters` in `cls.__dict__` + resolved `_filterset` strings) is thoughtful and matches the circular-import story.
- `QuerySetProxy` correctly composes `Q` for `filter` / `exclude`, including single-`Q` argument forms.
- `check_permissions` delegation through related prefixes matches how expanded filter keys are named.

---

**Summary:** The biggest issue is **hardcoded `and` / `or` / `not` vs configurable `settings.AND_KEY` / `OR_KEY` / `NOT_KEY`**, which breaks non-default library configuration. Next is **`find_filter` possibly returning `None`** and blowing up in `get_queryset_proxy_for_form`. After that: overly broad `except Exception` in `expand_auto_filter`, and search / docstring mismatch.
