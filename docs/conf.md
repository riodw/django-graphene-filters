## Review: `django_graphene_filters/conf.py`

### High: `DJANGO_GRAPHENE_FILTERS = None` breaks attribute access

`user_settings` is set with:

```88:90:django_graphene_filters/conf.py
        if self._user_settings is None:
            self._user_settings = getattr(django_settings, DJANGO_SETTINGS_KEY, {})
        return self._user_settings
```

If the project defines `DJANGO_GRAPHENE_FILTERS = None` (key present, value `None`), `user_settings` becomes `None`. Then `__getattr__` does `if name in self.user_settings`, which raises `TypeError`. A safe pattern is to normalize to a dict (e.g. `getattr(..., {}) or {}`).

---

### High: “Fixed” DB flags are fixed for the process

`get_fixed_settings()` is `@cache`d, and `FIXED_SETTINGS` is assigned once at import:

```36:70:django_graphene_filters/conf.py
@cache
def get_fixed_settings() -> dict[str, bool]:
    ...
FIXED_SETTINGS = get_fixed_settings()
```

`reload_settings` only rebuilds the `Settings` wrapper when `DJANGO_GRAPHENE_FILTERS` changes; it does **not** clear `get_fixed_settings.cache_clear()` or refresh `FIXED_SETTINGS`. So `IS_POSTGRESQL` / `HAS_TRIGRAM_EXTENSION` stay whatever they were on **first import**, even if:

- the database becomes available later,
- tests swap `DATABASES`,
- or you move from SQLite to PostgreSQL without restarting the process.

That can leave full-text/trigram behavior wrong until a full reload.

---

### Medium: `reload_settings` passes `value` into `Settings(value)`

On `setting_changed`, the new value is passed in as `_user_settings`. That matches the override path when Django notifies with the new dict. No issue there, as long as the signal always sends a dict; if it ever sent `None`, you’d hit the same bug as above.

---

### Low: `check_pg_trigram_extension` assumes PostgreSQL

It is only called when `connection.vendor == "postgresql"`, so the `pg_extension` query is not run on SQLite. Fine.

---

### Low: Confusing exports / names

The module defines `IS_POSTGRESQL = "IS_POSTGRESQL"` as a **string key** constant, while `settings.IS_POSTGRESQL` returns a **boolean** from `FIXED_SETTINGS`. Anyone doing `from django_graphene_filters.conf import IS_POSTGRESQL` may think they’re importing the flag, not the setting name string.

---

### Low: Stray comments

The `# 4`, `# 3`, `# 2`, `# 1` comments before `FIXED_SETTINGS` / `reload_settings` look accidental.

---

**Summary:** The important issues are robustness when `DJANGO_GRAPHENE_FILTERS` is `None`, and **staleness of PostgreSQL/trigram detection** because of `@cache` plus a module-level `FIXED_SETTINGS` snapshot that `reload_settings` never invalidates. Addressing those would make settings behave correctly across DB changes and odd Django settings values.
