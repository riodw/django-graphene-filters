## Review: `django_graphene_filters/input_types.py`

### High: `SearchQueryInputType` freezes AND/OR/NOT field names at import time

`SearchQueryInputType` is built once when the module loads:

```97:98:django_graphene_filters/input_types.py
# Initialize the SearchQueryInputType
SearchQueryInputType = create_search_query_input_type()
```

Inside `create_search_query_input_type`, the GraphQL field names for the logical operators come from **whatever `settings.AND_KEY` / `OR_KEY` / `NOT_KEY` are at that moment**:

```73:84:django_graphene_filters/input_types.py
        settings.AND_KEY: graphene.InputField(
            graphene.List(graphene.NonNull(lambda: SearchQueryInputType)),
            ...
        ),
        settings.OR_KEY: graphene.InputField(
            ...
        ),
        settings.NOT_KEY: graphene.InputField(
            graphene.List(graphene.NonNull(lambda: SearchQueryInputType)),
            ...
        ),
```

If `DJANGO_GRAPHENE_FILTERS` is updated later (tests, `override_settings`, or your `setting_changed` handler), this class is **not** rebuilt. The schema keeps the old attribute names while `input_data_factories` / other code might start using the new keys — a real desync. Fixing this in general means rebuilding the type when those settings change, or avoiding dynamic class attributes tied to mutable settings.

---

### Medium: `NOT` is modeled as a list (and mismatches `create_search_query`)

`NOT_KEY` uses `graphene.List(graphene.NonNull(lambda: SearchQueryInputType))`, same shape as AND/OR. In `input_data_factories.create_search_query`, `NOT` is handled as a **single** nested input:

```205:206:django_graphene_filters/input_data_factories.py
    not_input_type = input_type.get(settings.NOT_KEY)
    not_search_query = create_search_query(not_input_type) if not_input_type else None
```

So a client sending a non-empty list for `not` (as the schema allows) does not match this code path. Either the schema should be a single nested input, or the factory should iterate / reduce the list like AND/OR.

---

### Low: `SearchQuery.search_type` is documented but not exposed

The docstring and TODO correctly note that Django’s `SearchQuery` supports `search_type` (`plain` / `phrase` / `raw` / `websearch`) but the input type only has `value` and `config`. That is a product limitation, not a runtime bug, unless users assume parity with Django’s API.

---

### Low: `SearchRankWeightsInputType` doc links Django 3.2

The weights match Django’s documented defaults; the link is just an older minor version. Harmless but easy to refresh.

---

### Low: `FloatLookupsInputType` allows an empty object

All lookup fields are optional, so `{}` is valid GraphQL input until something downstream validates “at least one lookup”. Failures may surface late in filter execution rather than at input validation.

---

### What looks solid

- Self-referential `SearchQueryInputType` via lambdas is a standard Graphene pattern; resolution happens after the module assigns `SearchQueryInputType`, so the forward reference works at runtime.
- `SearchQueryFilterInputType` / `SearchRankFilterInputType` / `TrigramFilterInputType` are clearly separated and line up with the factories keyed by `postfix`.
- `TrigramSearchKind` defaulting to `SIMILARITY` is explicit and matches typical usage.

---

**Summary:** The main issues are **import-time binding of logical-operator keys** on `SearchQueryInputType` (stale vs `setting_changed` / tests) and the **NOT field typed as a list while `create_search_query` treats it as one node**. The rest is mostly API completeness (`search_type`) and validation strictness on float lookups.
