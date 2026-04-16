# Spec: Async + Query Consolidation for `AdvancedAggregateSet`

**Status:** Draft
**Scope:** `django_graphene_filters/aggregateset.py` (primary),
`connection_field.py` (secondary)
**Goal:** Reduce per-request DB roundtrips for aggregate computations and
expose an async code path for apps that want it — without adding
threading primitives that fight Django's connection model.

---

## 1. Overview

`AdvancedAggregateSet.compute()` currently issues **one DB query per
stat per field**, and re-fetches values lists from the DB once per
Python-level stat. For a config like:

```python
class ObjectAggregate(AdvancedAggregateSet):
    class Meta:
        model = Object
        fields = {
            "name": ["count", "min", "max", "mode", "uniques"],
            "created_date": ["count", "min", "max"],
        }
```

a single GraphQL request that selects every stat triggers on the order
of **10+ sequential queries** for just the top-level. With a
`RelatedAggregate` fan-out (e.g. `Object → Values → Attribute`), that
number multiplies. The pipeline is I/O-bound and entirely unconcurrent.

Two orthogonal improvements address this:

1. **Query consolidation** — collapse DB-level stats into a single
   `.aggregate()` call per queryset, and fetch Python-stat value lists
   once per field rather than once per stat.
2. **Async variant** — expose an `acompute()` path that parallelizes
   `RelatedAggregate` traversals with `asyncio.gather` for apps running
   on ASGI.

Threading (`ThreadPoolExecutor`, bare `threading.Thread`) is
deliberately **out of scope** — see §7.

---

## 2. Goals / Non-Goals

### Goals

- Reduce per-field stat computation from O(stats) queries to O(1).
- Reduce Python-stat value fetches from O(stats_per_field) to
  O(fields).
- Preserve current public API: `compute()` returns the same dict shape.
- Preserve selection-set awareness, per-field / per-stat permission
  hooks, `custom_stats`, and `compute_<field>_<stat>()` overrides.
- Offer opt-in async traversal for `RelatedAggregate` fan-out without
  changing the sync default.

### Non-Goals

- Changing the schema (InputObjectTypes / ObjectTypes) or GraphQL
  behaviour as observed by the client.
- Changing the per-stat GraphQL output types (`STAT_TYPES` stays as-is).
- Introducing new stat names.
- Migrating the non-aggregate code paths (filterset, orderset) — they
  are already single-query or laz y-evaluated.
- Adding threading primitives (see §7 for rationale).

---

## 3. Current State (as of 0.7.4)

### 3.1 `STAT_REGISTRY`

```python
# aggregateset.py
STAT_REGISTRY: dict[str, Any] = {
    "count":        lambda qs, f: qs.exclude(**{f: None}).values(f).distinct().count(),
    "min":          lambda qs, f: qs.aggregate(v=Min(f))["v"],
    "max":          lambda qs, f: qs.aggregate(v=Max(f))["v"],
    "sum":          lambda qs, f: qs.aggregate(v=Sum(f))["v"],
    "mean":         lambda qs, f: qs.aggregate(v=Avg(f))["v"],
    "median":       _py_median,    # fetches values, runs statistics.median
    "mode":         _py_mode,      # fetches values, runs statistics.mode
    "stdev":        _py_stdev,     # fetches values, runs statistics.stdev
    "variance":     _py_variance,  # fetches values, runs statistics.variance
    "uniques":      _uniques,      # values(field).annotate(Count("*"))
    "true_count":   _bool_true_count,
    "false_count":  _bool_false_count,
}
```

Every lambda/function is called atomically as `func(qs, field) → value`
inside `compute()`. Four independent DB queries for `min` + `max` +
`sum` + `mean` on one field. Four DB fetches of the same values list
for `median` + `mode` + `stdev` + `variance`.

### 3.2 `compute()` shape

```python
def compute(self, selection_set=None, local_only=False):
    result = {"count": self.queryset.count()}       # query 1
    requested = self._parse_selection_set(selection_set)
    for field_name, cfg in self._aggregate_config.items():
        # ... permission + selection gates ...
        field_result = {}
        for stat_name in cfg["stats"]:
            # ... per-stat permission + selection gate ...
            field_result[stat_name] = STAT_REGISTRY[stat_name](qs, field)  # query N
        result[field_name] = field_result
    # related aggregates — recursive sequential compute()
    ...
```

---

## 4. Priority 1 — Consolidate DB-level aggregates

### 4.1 Change

Reshape `STAT_REGISTRY` into three categories so `compute()` can collect
all DB-level work into a single `.aggregate(**kwargs)` call before
falling back to Python and per-field helpers.

```python
# NEW — replaces the monolithic STAT_REGISTRY

# Category A: DB aggregate expressions — contributions to a single
# .aggregate(**kwargs) call. Each entry is a callable
# (field_name: str) -> Aggregate that returns the Django expression.
DB_AGGREGATES: dict[str, Callable[[str], Aggregate]] = {
    "count":       lambda f: Count(f, distinct=True),
    "min":         lambda f: Min(f),
    "max":         lambda f: Max(f),
    "sum":         lambda f: Sum(f),
    "mean":        lambda f: Avg(f),
    "true_count":  lambda f: Count("pk", filter=Q(**{f: True})),
    "false_count": lambda f: Count("pk", filter=Q(**{f: False})),
}

# Category B: Python stats — operate on a pre-fetched values list.
# Fetch once per field; reuse the list across every Python stat.
PYTHON_STATS: dict[str, Callable[[list], Any]] = {
    "median":   lambda vs: statistics.median(vs) if vs else None,
    "mode":     _py_mode_from_values,      # handles StatisticsError
    "stdev":    lambda vs: round(statistics.stdev(vs), 2) if len(vs) > 1 else None,
    "variance": lambda vs: round(statistics.variance(vs), 2) if len(vs) > 1 else None,
}

# Category C: Special — stats that don't fit the above moulds.
# Currently just "uniques" (needs its own GROUP BY query).
SPECIAL_STATS: dict[str, Callable[[QuerySet, str], Any]] = {
    "uniques": _uniques,
}
```

### 4.2 New `compute()` structure

Three phases: **plan → execute → assemble**.

```python
def compute(self, selection_set=None, local_only=False):
    requested = self._parse_selection_set(selection_set)
    result: dict[str, Any] = {"count": self.queryset.count()}

    # ───────── Phase 1: PLAN ─────────
    agg_kwargs: dict[str, Aggregate] = {}       # → one .aggregate() call
    py_fields: dict[str, list[str]] = {}        # field → [stat, ...]
    special: list[tuple[str, str]] = []         # (field, stat)
    custom: list[tuple[str, str, Callable]] = []  # (field, stat, method)

    for field_name, cfg in self._aggregate_config.items():
        if requested is not None and field_name not in requested:
            continue
        self._check_field_permission(field_name)

        for stat_name in cfg["stats"]:
            if requested is not None:
                fr = requested.get(field_name)
                if fr is not None and stat_name not in fr:
                    continue
            self._check_stat_permission(field_name, stat_name)

            # Resolution order mirrors the current behaviour:
            #   1. compute_<field>_<stat>() override → custom
            #   2. DB aggregate → agg_kwargs
            #   3. Python stat → py_fields
            #   4. Special → special
            method = getattr(self, f"compute_{field_name}_{stat_name}", None)
            if method:
                custom.append((field_name, stat_name, method))
            elif stat_name in DB_AGGREGATES:
                alias = _alias(field_name, stat_name)
                agg_kwargs[alias] = DB_AGGREGATES[stat_name](field_name)
            elif stat_name in PYTHON_STATS:
                py_fields.setdefault(field_name, []).append(stat_name)
            elif stat_name in SPECIAL_STATS:
                special.append((field_name, stat_name))

    # ───────── Phase 2: EXECUTE ─────────
    agg_results = self.queryset.aggregate(**agg_kwargs) if agg_kwargs else {}

    py_results: dict[str, dict[str, Any]] = {}
    for field_name, stat_names in py_fields.items():
        values = _fetch_values(self.queryset, field_name)  # ← ONCE per field
        py_results[field_name] = {s: PYTHON_STATS[s](values) for s in stat_names}

    special_results = {(f, s): SPECIAL_STATS[s](self.queryset, f) for f, s in special}
    custom_results = {(f, s): m(self.queryset) for f, s, m in custom}

    # ───────── Phase 3: ASSEMBLE ─────────
    for field_name, cfg in self._aggregate_config.items():
        if requested is not None and field_name not in requested:
            continue
        field_result: dict[str, Any] = {}
        for stat_name in cfg["stats"]:
            if requested is not None:
                fr = requested.get(field_name)
                if fr is not None and stat_name not in fr:
                    continue
            alias = _alias(field_name, stat_name)
            if alias in agg_results:
                field_result[stat_name] = agg_results[alias]
            elif field_name in py_results and stat_name in py_results[field_name]:
                field_result[stat_name] = py_results[field_name][stat_name]
            elif (field_name, stat_name) in special_results:
                field_result[stat_name] = special_results[(field_name, stat_name)]
            elif (field_name, stat_name) in custom_results:
                field_result[stat_name] = custom_results[(field_name, stat_name)]
        result[field_name] = field_result

    if local_only:
        return result
    # ... related aggregates unchanged for now — see §6
    return result


def _alias(field: str, stat: str) -> str:
    """Alias for .aggregate() kwargs. Must be a valid Python identifier
    and not collide with model field names — `_agg_` prefix handles both."""
    return f"_agg_{field}_{stat}"
```

### 4.3 Expected DB impact

| Config | Before | After |
|---|---:|---:|
| `{"name": ["min", "max"]}` | 2 queries | 1 query |
| `{"name": ["count","min","max","sum","mean"]}` | 5 | 1 |
| `{"name": ["median","mode","stdev","variance"]}` | 4 fetches | 1 fetch |
| `{"name": ["count","min","max","mode"], "age": ["min","max","mean"]}` | 7 | 1 + 1 fetch |
| Full config (mixed DB + Python + special) | N+M+K | 1 + F + S |

…where `F` = fields with ≥1 Python stat and `S` = special stats.

### 4.4 Semantic equivalence: `count`

Current: `qs.exclude(**{f: None}).values(f).distinct().count()`
Proposed: `Count(f, distinct=True)` inside `.aggregate()`

Both yield `COUNT(DISTINCT f)` with SQL-standard null-exclusion
semantics. The subquery form the current code emits is a superset of
work the DB would otherwise do inline. **Must be verified** with an
integration test that asserts equal counts across:

- Non-nullable field with duplicates
- Nullable field with NULLs and duplicates
- Queryset with prior `.filter()` / `.annotate()` steps
- Queryset produced by `get_child_queryset()` (which applies
  `.distinct()` for M2M traversals)

### 4.5 Risks

- **Aggregates + annotate interaction.** The proposed consolidation
  runs `.aggregate(**many)` on `self.queryset`, which may already carry
  annotations from earlier filter steps (e.g. `SearchVector`,
  `TrigramSimilarity`). `.aggregate()` does accept this, but the
  execution plan can differ from today's per-stat subquery form. CI
  coverage for search-filtered aggregates is required.

- **`true_count`/`false_count` currently use `.filter().count()`.**
  Replacing with `Count("pk", filter=Q(**{f: True}))` is equivalent on
  PostgreSQL and SQLite 3.30+ but triggers the `FILTER (WHERE …)`
  clause — confirm the `BooleanFilter` tests pass on the minimum
  supported SQLite version.

- **Alias collisions.** A user's model field named `_agg_…` would break.
  The prefix is deliberately unusual; document it.

- **Ordering of query cost.** One big `.aggregate()` call runs every
  aggregate even if downstream only reads some. The planner today
  avoided unused computation by not issuing the query at all — but the
  plan phase still respects `selection_set`, so only *requested* stats
  enter `agg_kwargs`. Unused stats never reach the DB.

### 4.6 Testing

Existing `tests/test_aggregate_*.py` files already cover per-stat
correctness. To validate consolidation:

1. **Equivalence matrix** — for each field category (text, numeric,
   datetime, boolean) run the full stat list under both the old and
   new code path, assert byte-identical output.
2. **Query count assertion** — use `django.test.utils.CaptureQueriesContext`
   to assert the new path issues exactly the expected number of
   queries for representative configs.
3. **Selection-set subsetting** — when only `min` is requested, assert
   only one `.aggregate()` call with a single kwarg (not the full
   config).
4. **Interaction tests** — run aggregate computation on querysets
   carrying prior `.annotate()` (search filter output) and
   `.filter()` clauses.

---

## 5. Priority 2 — DB-native Python stats (PostgreSQL)

### 5.1 Motivation

`median`, `stdev`, `variance` currently fetch every value into Python
(capped at `AGGREGATE_MAX_VALUES=10000`) and compute in-memory. When
the queryset is on PostgreSQL, the same operations are available
natively and operate on the full result set without the memory cap:

| Stat | Python (current) | PostgreSQL expression |
|---|---|---|
| `median` | `statistics.median` over fetched list | `PercentileCont(0.5).within_group(F(f).asc())` |
| `stdev` | `statistics.stdev` | `StdDev(f)` |
| `variance` | `statistics.variance` | `Variance(f)` |
| `mode` | `statistics.mode` | `Mode().within_group(F(f).asc())` (requires PG ≥ 9.4 + Django ≥ 4.0) |

### 5.2 Change

Add a PostgreSQL-only path controlled by `settings.IS_POSTGRESQL`
(already exported from `conf.py`). In the plan phase:

```python
if stat_name in PYTHON_STATS:
    if settings.IS_POSTGRESQL and stat_name in DB_NATIVE_PERCENTILE_STATS:
        alias = _alias(field_name, stat_name)
        agg_kwargs[alias] = DB_NATIVE_PERCENTILE_STATS[stat_name](field_name)
    else:
        py_fields.setdefault(field_name, []).append(stat_name)
```

Where:

```python
from django.db.models import StdDev, Variance
from django.db.models.functions import PercentileCont, Mode

DB_NATIVE_PERCENTILE_STATS = {
    "median":   lambda f: PercentileCont(0.5).within_group(F(f).asc()),
    "stdev":    lambda f: StdDev(f),
    "variance": lambda f: Variance(f),
    "mode":     lambda f: Mode().within_group(F(f).asc()),
}
```

### 5.3 Impact

- Removes the `AGGREGATE_MAX_VALUES=10000` truncation warning for
  `median`/`stdev`/`variance`/`mode` on PostgreSQL — stats become exact.
- Folds these stats into the consolidated `.aggregate()` call from §4,
  so they add zero additional queries.
- On SQLite/MySQL, behaviour is unchanged (fall back to Python).

### 5.4 Risks

- **Rounding differences.** `statistics.stdev` uses Bessel's correction
  and rounds to 2 d.p. (`round(..., 2)`). Django's `StdDev` defaults to
  `sample=False` (population stdev) — must pass `sample=True` to match.
  Same for `Variance`. Rounding should be applied in the assemble phase
  so output stays bit-identical per backend.
- **Vendor detection.** `settings.IS_POSTGRESQL` comes from `get_fixed_settings()`
  which caches at import time. Test suites swapping `DATABASES` already
  trigger `reload_settings` (see `conf.py:111`) — verify the refresh
  covers this code path.
- **`Mode` requires Django 4.0+.** Project currently supports Django
  5.2+, so this is fine — just document it.

### 5.5 Tests

Add parametrized tests that assert:

- On PostgreSQL: `median` returned for a 100k-row dataset is exact
  (matches `statistics.median` over the full list, not a 10k sample).
- On SQLite: behaviour is unchanged; the `AGGREGATE_MAX_VALUES` warning
  still fires beyond the cap.
- `round(..., 2)` parity between both backends for `stdev`/`variance`.

---

## 6. Priority 3 — Async `acompute()` for `RelatedAggregate` fan-out

### 6.1 When this helps

Sync `compute()` recurses sequentially through every `RelatedAggregate`:

```python
for rel_name, rel_agg in self.__class__.related_aggregates.items():
    child_qs = self.get_child_queryset(rel_name, rel_agg)
    child_agg = rel_agg.aggregate_class(queryset=child_qs, request=self.request)
    result[rel_name] = child_agg.compute(selection_set=child_selection)
```

Each child `compute()` is now (post-§4) a ~2-query workload. With 5
related aggregates that is 10 sequential queries — roughly 10 × network
latency. Under ASGI, these can run concurrently with `asyncio.gather`
and finish in ~2 round-trips of wall time.

Note: concurrency only pays off with meaningful network latency
(production DB on another host). For on-box SQLite in tests it's a no-op
or net negative.

### 6.2 API

Opt-in async variant alongside the sync method:

```python
class AdvancedAggregateSet(metaclass=AggregateSetMetaclass):
    def compute(self, selection_set=None, local_only=False) -> dict[str, Any]:
        """Sync entrypoint (unchanged public contract)."""
        ...

    async def acompute(self, selection_set=None, local_only=False) -> dict[str, Any]:
        """Async variant. Identical output; parallelizes RelatedAggregate traversals."""
        ...
```

Clients on ASGI (e.g. Graphene's async resolvers) call `acompute()`;
legacy sync callers call `compute()`. Neither is preferred — the right
choice depends on the host app's runtime.

### 6.3 Implementation sketch

```python
from asgiref.sync import sync_to_async
import asyncio

async def acompute(self, selection_set=None, local_only=False):
    # Phase 1–3 (own-field stats) runs via sync_to_async since the
    # ORM paths we call (count, aggregate, values) are thread-sensitive.
    base_result = await sync_to_async(
        self._compute_own_fields, thread_sensitive=True
    )(selection_set)

    if local_only:
        return base_result

    # Fan out RelatedAggregates concurrently.
    requested = self._parse_selection_set(selection_set)
    coros = []
    names: list[str] = []
    for rel_name, rel_agg in self.__class__.related_aggregates.items():
        if requested is not None and rel_name not in requested:
            continue
        child_selection = self._get_child_selection(selection_set, rel_name)
        coros.append(self._acompute_related(rel_name, rel_agg, child_selection))
        names.append(rel_name)

    for name, child_result in zip(names, await asyncio.gather(*coros), strict=True):
        base_result[name] = child_result
    return base_result


async def _acompute_related(self, rel_name, rel_agg, child_selection):
    child_qs = await sync_to_async(self.get_child_queryset, thread_sensitive=True)(
        rel_name, rel_agg
    )
    child_agg = rel_agg.aggregate_class(queryset=child_qs, request=self.request)
    return await child_agg.acompute(selection_set=child_selection)
```

The existing sync `compute()` body should be refactored into a private
`_compute_own_fields(selection_set) -> dict` helper so both entrypoints
call it.

### 6.4 Connection semantics

- Each `sync_to_async(..., thread_sensitive=True)` call routes through
  Django's thread-sensitive executor, which reuses the **same thread**
  for the same async task. This preserves `ATOMIC_REQUESTS` transaction
  semantics — the ORM operations all run on a single connection for the
  life of one GraphQL request.
- Concurrent `_acompute_related` calls each kick off their own
  thread-sensitive tasks. Django serialises their DB work on the same
  connection unless the host uses `thread_sensitive=False` explicitly
  (not what we want here).
- So **"concurrent" here means concurrent at the asyncio-task level,
  not the DB level** when `thread_sensitive=True`. The performance win
  comes primarily from overlapping child computations that *don't*
  share the DB connection path — e.g. I/O-bound custom
  `compute_<field>_<stat>()` methods calling external services.

For truly parallel DB traversal, an app would need
`thread_sensitive=False` + explicit connection management. That is too
invasive for a library default and explicitly **not** part of this
spec.

### 6.5 Conclusion on async priority

Given §6.4, the actual speedup from `acompute()` on pure-ORM workloads
is modest — the main gain is graceful integration with async
resolvers, not parallelism. **Recommendation:** implement `acompute()`
only after §4 and §5 ship, and scope it narrowly as "async-compatible
wrapper", not "parallel speedup". Document the thread-sensitive
trade-off explicitly.

### 6.6 Risks

- Consumers may assume `acompute()` gives free parallelism. Docs must
  be blunt about the thread-sensitive mode and its implications.
- `request` is plumbed through permission methods; passing it across an
  async boundary is fine (read-only) but must not be mutated.
- The sync and async paths must share a single source of truth for the
  plan/execute/assemble phases — hence the `_compute_own_fields`
  helper. Two implementations drifting apart is the biggest ongoing
  maintenance risk.

---

## 7. Out of scope: `ThreadPoolExecutor`

Explicitly **not** proposed, despite superficial appeal:

1. **Connection ownership.** Django DB connections are per-thread.
   Spawning threads inside a resolver means each thread checks out its
   own connection, bypassing any request-scoped `ATOMIC_REQUESTS`
   transaction. Users who rely on transactional isolation would see
   silent breakage.
2. **Connection leaks.** Threads must call
   `django.db.connections.close_all()` on exit; easy to forget, hard to
   detect until `CONN_MAX_AGE` expires under load.
3. **Pool exhaustion.** `N concurrent requests × M threads per request`
   saturates the DB pool under traffic — a library-level choice that
   leaks out to every consumer's ops team.
4. **GIL-bound work.** Python-level stats (`statistics.median` etc.)
   are CPU-bound; threads help only for I/O, and the I/O here is
   already batched into one query by §4.
5. **Async is the sanctioned answer.** Django 4.1+ has first-class async
   ORM APIs. A library that wants to offer concurrency should expose an
   async path (§6), not ship threads. Consumers who need threads have
   `sync_to_async(..., thread_sensitive=False)` available in their own
   code.

Any future contributor tempted to add threading here should re-read
this section and check with maintainers first.

---

## 8. Implementation Plan

Ship in ordered, independently revertable PRs. Each depends on its
predecessor only for code hygiene (shared helpers), not for behaviour.

| # | PR title | Files | Risk |
|---|---|---|---|
| 1 | Split `STAT_REGISTRY` into `DB_AGGREGATES` / `PYTHON_STATS` / `SPECIAL_STATS` | `aggregateset.py` | Low — mechanical |
| 2 | Refactor `compute()` into plan/execute/assemble phases | `aggregateset.py` | **Medium** — main behaviour change; gated on new CaptureQueriesContext tests |
| 3 | Memoize `_fetch_values` per field within `compute()` | `aggregateset.py` | Low |
| 4 | Add `DB_NATIVE_PERCENTILE_STATS` + PG detection branch | `aggregateset.py`, `conf.py` (no change) | Medium — rounding parity tests required |
| 5 | Extract `_compute_own_fields` helper | `aggregateset.py` | Low |
| 6 | Add `acompute()` with `asyncio.gather` over RelatedAggregates | `aggregateset.py`, plus Graphene async resolver wiring in `connection_field.py` | Medium — requires ASGI test infra |
| 7 | Documentation updates (`CHANGELOG.md`, README, docstrings) | docs | Low |

PRs #1–#4 deliver the full query-consolidation win and can ship
without any async work. PRs #5–#6 are decoupled and can be deferred
pending real-world demand for async resolvers.

---

## 9. Backward Compatibility

### Breaks nothing externally

- `compute()` signature unchanged.
- Return dict shape unchanged (same keys, same value types).
- `Meta.custom_stats` still supported.
- `compute_<field>_<stat>()` overrides still called first.
- `STAT_REGISTRY` symbol — `aggregateset.STAT_REGISTRY` is currently
  module-level but **not** listed in `__all__` or `__init__.py`. If
  external code imports it, keep it as a computed read-only alias:

  ```python
  # Preserved for backward compat; new code should not depend on this.
  STAT_REGISTRY = {**DB_AGGREGATES, **PYTHON_STATS, **SPECIAL_STATS}
  ```

### Observable behaviour changes

- Total query count per request goes down (observable via
  `django-debug-toolbar`, `CaptureQueriesContext`).
- On PostgreSQL, `median`/`mode`/`stdev`/`variance` become **exact**
  rather than truncated at `AGGREGATE_MAX_VALUES`. Users who relied on
  the sampling behaviour will see different values. **Document this
  loudly in the CHANGELOG.**
- The truncation warning for Python-side stats no longer fires on
  PostgreSQL.

---

## 10. Testing Plan

1. **Equivalence** — existing `test_aggregate_*.py` suite must pass
   unchanged. Add parametrized tests that run each category of stat
   through both the old code path (kept under a feature flag for one
   release) and the new path, asserting dict equality.
2. **Query count** — `CaptureQueriesContext` assertions for the
   representative configs in §4.3 table.
3. **Selection-set subsetting** — assert that requesting `min` only
   issues a single-kwarg `.aggregate()` call, never a full-config one.
4. **Interaction with search filters** — aggregate computation on
   search-annotated querysets must still return correct values.
5. **`get_child_queryset` edge cases** — M2M traversal with
   `.distinct()` must still produce correct counts post-consolidation.
6. **PG native stats (priority 5)** — run against both PostgreSQL and
   SQLite in CI; assert:
   - PG: `median`/`stdev`/`variance` match `statistics` over the full
     dataset (no truncation).
   - SQLite: behaviour unchanged; truncation warning still fires.
   - Rounding is identical to 2 d.p. across backends.
7. **Async (priority 6)** — add an ASGI test client; assert
   `acompute()` output equals `compute()` output for the same selection.
   Use `aiohttp` or `httpx.AsyncClient` against Django's `AsgiHandler`.
8. **Regression** — keep the existing `AGGREGATE_MAX_VALUES` truncation
   warning test, but scope it to non-PG backends (and to `uniques`,
   which always truncates regardless of backend).

---

## 11. Open Questions

1. **Should `STAT_REGISTRY` be kept as a public alias?** If any third
   party depends on it, removing it is a breaking change. Needs a grep
   across common consumers before deciding.
2. **PG mode stat via `Mode()`** — Django 4.0+. Current project
   `requires-python>=3.10` and Django 5.2+, so fine. Confirm in CI
   matrix.
3. **Do we want to expose `acompute()` on the connection field?** The
   current aggregate injection in `_inject_aggregates_on_connection`
   uses a sync `resolve_aggregates`. Adding an async variant means the
   resolver dispatches on `info.context`'s loop — worth prototyping
   before committing to a public API.
4. **Backward-compat window for `STAT_REGISTRY` alias** — one minor
   release (e.g. 0.8.0 ships the alias, 0.9.0 removes it) or keep it
   indefinitely as a read-only computed dict?

---

## 12. Appendix — `_fetch_values` memoization

Even without the full §4 refactor, a tiny targeted change gives ~4x
fewer DB fetches on Python-stat-heavy configs:

```python
# aggregateset.py – inside compute()
_values_cache: dict[str, list] = {}

def _get_values(field_name: str) -> list:
    if field_name not in _values_cache:
        _values_cache[field_name] = _fetch_values(self.queryset, field_name)
    return _values_cache[field_name]
```

and replace each `_fetch_values(qs, field)` call site with
`_get_values(field)`. This is a 5-line change that lands
independently of the main refactor and is worth doing as a first-step
win even if §4 slips.
