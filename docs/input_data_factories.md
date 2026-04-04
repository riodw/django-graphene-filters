## Review: `django_graphene_filters/input_data_factories.py`

### High: `tree_input_type_to_data` hardcodes `"and"`, `"or"`, `"not"`

The main filter tree is built in `FilterArgumentsFactory` with `settings.AND_KEY`, `settings.OR_KEY`, and `settings.NOT_KEY`, but conversion still checks fixed strings:

```53:58:django_graphene_filters/input_data_factories.py
    for key, value in tree_input_type.items():
        # Handling logical operations on the filter set
        if key in ("and", "or"):
            result[key] = [tree_input_type_to_data(filterset_class, subtree) for subtree in value]
        elif key == "not":
            result[key] = tree_input_type_to_data(filterset_class, value)
```

If `DJANGO_GRAPHENE_FILTERS` renames those keys, GraphQL will send the new names and **nested AND/OR/NOT will be treated as normal filter branches**, producing wrong `create_data` keys and broken filter trees. This matches the same configuration bug called out for `filterset.py` / `TreeFormMixin` / `create_form`.

**Fix direction:** use `settings.AND_KEY`, `settings.OR_KEY`, and `settings.NOT_KEY` here (and keep `result[...]` keys aligned with what `AdvancedFilterSet` expects after you fix the filterset side).

---

### Medium: `SearchQueryInputType` declares NOT as a list, `create_search_query` treats it as one value

In `input_types.py`, `NOT_KEY` is a `graphene.List(...)` like AND/OR. In `create_search_query`:

```205:206:django_graphene_filters/input_data_factories.py
    not_input_type = input_type.get(settings.NOT_KEY)
    not_search_query = create_search_query(not_input_type) if not_input_type else None
```

There is no `for` loop; a list from the client is passed straight into `create_search_query`, which expects a mapping-like node with `.get` / validation. The root filter input’s NOT field is a **single** nested object (`filter_arguments_factory`), so the design is inconsistent in two places: filter vs search-query input, and schema vs handler for search NOT.

---

### Medium: Combining `value` with AND/OR/NOT uses a flat `&` chain

```207:209:django_graphene_filters/input_data_factories.py
    valid_queries = (q for q in (and_search_query, or_search_query, not_search_query) if q is not None)
    for valid_query in valid_queries:
        search_query = search_query & valid_query if search_query else valid_query
```

This always combines the optional `value` query and the AND/OR/NOT-derived parts with **AND** in a fixed order `(and_group, or_group, not_group)`, not as an arbitrary tree. That is weaker than PostgreSQL `SearchQuery`’s real structure and can disagree with user intent when several branches are present (e.g. mixing top-level `value` with OR).

---

### Low: `DATA_FACTORIES` uses substring matching

```76:78:django_graphene_filters/input_data_factories.py
    for factory_key, factory in DATA_FACTORIES.items():
        if factory_key in key:
            return factory(value, key, filterset_class)
```

`factory_key in key` can match unintended paths if a filter name accidentally contains another filter’s `postfix` as a substring. Ordering of `DATA_FACTORIES` defines precedence; it is fragile compared to suffix or segment-based matching.

---

### Low: PostgreSQL imports set to `None` on `ImportError`

Like `filters.py`, if the import fails, later calls that use `SearchVector`, `SearchQuery`, `SearchRank`, trigram types, etc. will fail at runtime if anything still invokes these paths. In practice FTS is usually gated by `settings.IS_POSTGRESQL`, but this module has no local guard.

---

### What looks solid

- `create_search_rank_data` and trigram key normalization with `DEFAULT_LOOKUP_EXPR` stripping is consistent with the filter naming scheme.
- `validate_search_vector_fields` / `validate_search_query` give clear `ValidationError` messages.
- Recursing nested `InputObjectTypeContainer` through `create_data` → `tree_input_type_to_data` is the right shape for nested filter objects.

---

**Summary:** The critical issue is **hardcoded logical keys in `tree_input_type_to_data`** vs configurable `settings.*_KEY` used everywhere else. Secondary issues are **NOT list vs single-value handling** for `SearchQueryInputType`, **oversimplified boolean composition** for search queries, and **substring-based** factory dispatch. Aligning tree parsing with `settings` (and with `AdvancedFilterSet` / forms) should be the first fix.
