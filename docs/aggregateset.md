## Review: `django_graphene_filters/aggregateset.py`

### High: `get_child_queryset()` only de-duplicates for real M2M
`get_child_queryset()` applies `.distinct()` only when `_is_m2m_lookup()` returns `True` (i.e. when the **lookup field on `target_model`** is a `ManyToManyField` / `ManyToManyRel`):

- For reverse/one-to-many style traversals (reverse FK represented by Django as `ManyToOneRel`), the join can still multiply parent rows, which can inflate:
  - the related aggregate’s root `count` (`child_qs.count()`)
  - and DB-level stats like `sum`/`mean`/`uniques` computed over the duplicated rows.

This isn’t covered by the unit tests, but it can surface if a consumer defines a `RelatedAggregate` using a reverse relation name and then requests that subtree in GraphQL.

```410:416
if self._is_m2m_lookup(target_model, rel_agg.field_name):
    qs = qs.distinct()
```

### Medium: Python-level stats may not match GraphQL numeric scalar types
For `median`, `mode`, `stdev`, `variance`, the helpers return Python values derived from `_fetch_values()`:
- `DecimalField` values may stay as `Decimal` (or become floats when `float(v)` is used for stdev/variance).
- The GraphQL schema declares numeric stats as `graphene.Float`.

Graphene usually coerces, but this can be a source of precision/serialization mismatches depending on the backend and Graphene version.

### Low: Potential “missing stat key” behavior for custom stats without a compute method
`compute()` only populates a stat if:
- there is `compute_<field>_<stat_name>()`, or
- the stat exists in `STAT_REGISTRY`.

If a stat is listed in `Meta.custom_stats` but no compute method exists (and it’s not in `STAT_REGISTRY`), the returned dict won’t contain that key. GraphQL will then resolve it as `null` (or omit depending on how Graphene resolves from dicts). This is likely intentional, but it’s an edge-case to be aware of.

### What looks good
- The metaclass validation already prevents the big schema-collision problems (reserved root `count` field and overlap between `Meta.fields` and `RelatedAggregate` attribute names).
- Selection-set parsing (`_parse_selection_set` / `_get_child_selection`) is designed to compute only requested stats/branches, and tests cover key branches.
- The numeric “distinct value count” behavior for per-field `count` is consistent with tests (root `count` is total rows; per-field `count` is distinct non-null values).

If you want, I can propose a targeted fix for the de-duplication gap (expanding the relation-kind detection beyond M2M) and add a cookbook-style test that reproduces inflated counts for reverse FK `RelatedAggregate` traversal.
