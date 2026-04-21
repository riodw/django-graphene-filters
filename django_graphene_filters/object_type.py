"""`AdvancedDjangoObjectType` class module.

Use this instead of `DjangoObjectType` when you need to declare
an `orderset_class` or `search_fields` in the Meta of your node type.
"""

import logging
import warnings
from collections.abc import Sequence
from datetime import date, datetime, timezone
from typing import Any

import graphene
from django.db import models
from graphene import Dynamic
from graphene.utils.str_converters import to_camel_case
from graphene_django import DjangoObjectType
from graphene_django.converter import convert_django_field, get_django_field_description
from graphene_django.fields import DjangoConnectionField, DjangoListField
from graphene_django.types import DjangoObjectTypeOptions

from . import conf as _conf

logger = logging.getLogger(__name__)

# Epoch fallbacks for auto_now / auto_now_add fields (which report no default).
_EPOCH_DATETIME = datetime(1970, 1, 1, tzinfo=timezone.utc)
_EPOCH_DATE = date(1970, 1, 1)


def _inject_aggregates_on_connection(
    node_cls: type,
    aggregate_class: type,
    connection_type: type,
) -> None:
    """Inject an ``aggregates`` field onto a connection type.

    Called during ``__init_subclass_with_meta__`` so that every connection
    using this node type — root-level or nested — gets the aggregates field.

    The resolver computes lazily from ``root.iterable`` (the queryset that
    graphene-django attaches to every connection instance).  For root-level
    connections where ``AdvancedDjangoFilterConnectionField`` pre-computes
    aggregates, the pre-computed result is used instead.
    """
    if hasattr(connection_type, "_aggregate_field_injected"):
        return

    from .aggregate_arguments_factory import AggregateArgumentsFactory

    # Under class-based naming the factory derives its root type name from
    # ``aggregate_class.__name__`` alone (see ``docs/spec-base_type_naming.md``).
    # Root-level and nested connections using the same AggregateSet therefore
    # share the same cached ``agg_type`` via the ``ObjectTypeFactoryMixin`` cache.
    factory = AggregateArgumentsFactory(aggregate_class)
    agg_type = factory.build_aggregate_type()

    # Add the field to the connection class's _meta.fields
    connection_type._meta.fields["aggregates"] = graphene.Field(
        agg_type,
        description="Aggregate statistics",
    )

    # Resolver dispatch map (evaluated at call time so ``settings`` swaps in
    # tests propagate correctly):
    #
    # 1. ``root.aggregates``               — already a dict, return directly.
    # 2. ``iterable._aggregate_set``       — root-level connection: the
    #    ``AdvancedDjangoFilterConnectionField.resolve_queryset`` hook
    #    stashed a pre-built aggregate set and the extracted selection
    #    on the queryset so we can run the full ``compute(..)`` (with
    #    ``RelatedAggregate`` traversal) lazily here — this is what lets
    #    the root path participate in the async dispatch below.
    # 3. ``root.iterable`` alone           — nested connection: build an
    #    aggregate set on the fly, scoped to this edge's queryset, and
    #    compute with ``local_only=True`` since the GraphQL query
    #    structure already expresses the nesting.
    #
    # Sync vs async: the ``ASYNC_AGGREGATES`` setting is an explicit
    # opt-in, not an event-loop probe. A caller inside ``asyncio.run(...)``
    # that invokes the schema synchronously would otherwise get back an
    # unawaited coroutine; requiring an explicit toggle makes the
    # resolver's return type deterministic per-deployment.
    def resolve_aggregates(root: Any, info: Any) -> Any:
        # Path 1: pre-computed aggregate dict (legacy / manually attached).
        if hasattr(root, "aggregates"):
            return root.aggregates

        iterable = getattr(root, "iterable", None)
        if iterable is None:
            return None

        # Read through the conf module (``_conf.settings.X``) rather than a
        # module-level ``from .conf import settings`` alias: ``reload_settings``
        # rebinds ``conf.settings`` on ``override_settings`` swaps, and a local
        # alias would still point at the pre-override instance.
        use_async = bool(_conf.settings.ASYNC_AGGREGATES)

        # Path 2: root-level connection — stored aggregate set carries the
        # request's GraphQL selection and needs the full RelatedAggregate
        # fan-out (i.e. NOT ``local_only``).
        pre_agg_set = getattr(iterable, "_aggregate_set", None)
        if pre_agg_set is not None:
            selection = getattr(iterable, "_aggregate_selection", None)
            if use_async:
                return pre_agg_set.acompute(selection_set=selection)
            return pre_agg_set.compute(selection_set=selection)

        # Path 3: nested connection — lazy per-edge computation.
        agg_set = aggregate_class(queryset=iterable, request=info.context)
        if use_async:
            return agg_set.acompute(local_only=True)
        return agg_set.compute(local_only=True)

    connection_type.resolve_aggregates = staticmethod(resolve_aggregates)
    connection_type._aggregate_field_injected = True


class AdvancedDjangoObjectType(DjangoObjectType):
    """A DjangoObjectType subclass that supports `orderset_class` and `search_fields` in Meta.

    Also overrides ``get_node`` so that when ``get_queryset`` hides a row
    (e.g. because it is private), non-nullable FK fields receive a redacted
    sentinel instance instead of ``None`` — which would otherwise cause a
    ``"Cannot return null for non-nullable field"`` GraphQL error.

    .. warning::

        When a FK traverses a hidden (sentinel) node, all objects
        downstream of that sentinel are also redacted — even if the
        current user has access to them individually.  Use
        ``apply_cascade_permissions`` to proactively exclude parent rows
        whose FK targets are hidden if this is unacceptable for your
        use case.
    """

    is_redacted = graphene.Boolean(
        required=True,
        description=(
            "True when this node is a redacted sentinel (pk=0). "
            "The real row exists but is hidden by get_queryset permissions."
        ),
    )

    class Meta:
        """Mark this type as abstract so it is not registered as a concrete node."""

        abstract = True

    @staticmethod
    def resolve_is_redacted(root: Any, info: Any) -> bool:
        """Return True when the instance is a sentinel (pk=0)."""
        return root.pk == 0

    @classmethod
    def __init_subclass_with_meta__(
        cls,
        orderset_class: type | None = None,
        search_fields: Sequence[str] | None = None,
        aggregate_class: type | None = None,
        fields_class: type | None = None,
        _meta: DjangoObjectTypeOptions | None = None,
        **options,
    ) -> None:
        """Capture ``orderset_class``, ``search_fields``, ``aggregate_class``, and ``fields_class``."""
        if not _meta:
            _meta = DjangoObjectTypeOptions(cls)
        _meta.orderset_class = orderset_class
        _meta.search_fields = search_fields
        _meta.aggregate_class = aggregate_class
        _meta.fields_class = fields_class
        super().__init_subclass_with_meta__(_meta=_meta, **options)

        # Inject aggregates field onto the connection type so it's available
        # on both root-level and nested connections (e.g. object.values.aggregates).
        if aggregate_class and hasattr(_meta, "connection") and _meta.connection:
            _inject_aggregates_on_connection(cls, aggregate_class, _meta.connection)

        # Wrap resolvers for fields managed by the FieldSet.
        if fields_class:
            _wrap_field_resolvers(cls, fields_class)

        # Sentinel / cascade permissions require Relay's get_node for FK
        # resolution.  Without the Node interface, FK fields resolve via
        # direct ORM attribute access, bypassing get_queryset entirely.
        interfaces = getattr(_meta, "interfaces", ()) or ()
        from graphene.relay import Node

        if not any(issubclass(i, Node) for i in interfaces):
            warnings.warn(
                f"{cls.__name__} does not implement the Relay Node interface. "
                "Sentinel and cascade permission behaviour for FK fields will "
                "not work — FK targets will resolve directly from the ORM, "
                "bypassing get_queryset. Add `interfaces = (graphene.relay.Node,)` "
                "to the Meta class to enable full permission support.",
                stacklevel=2,
            )

    @classmethod
    def _make_sentinel(cls, source_pk: Any = None) -> Any:
        """Create a redacted sentinel instance with ``pk=0``.

        If ``source_pk`` is provided, the sentinel copies the real FK IDs
        from the hidden row so that downstream FK resolution goes through
        ``get_node`` normally.  Visible targets resolve to real objects;
        hidden targets produce their own sentinels.

        This preserves consistency: if a user can see an ObjectType at the
        root level, they also see the real ObjectType when it appears
        through a hidden intermediate (e.g. a private Attribute).
        """
        sentinel = cls._meta.model(pk=0)
        # Only single-column FK/O2O fields — exclude ManyToManyField which
        # has attname and related_model but is backed by a join table and
        # cannot be assigned via setattr.
        fk_fields = [
            f
            for f in cls._meta.model._meta.get_fields()
            if hasattr(f, "column") and getattr(f, "related_model", None) is not None
        ]
        if source_pk is not None and fk_fields:
            # Copy real FK IDs so visible downstream targets resolve normally.
            attnames = [f.attname for f in fk_fields]
            real_values = cls._meta.model.objects.filter(pk=source_pk).values(*attnames).first()
            if real_values:
                for attname in attnames:
                    setattr(sentinel, attname, real_values[attname])
                return sentinel
        # Fallback: set FK IDs to 0 for safe chain propagation.
        for f in fk_fields:
            setattr(sentinel, f.attname, 0)
        return sentinel

    @classmethod
    def get_node(cls, info: Any, id: Any) -> Any | None:
        """Return the node for *id*, or a redacted sentinel if hidden by ``get_queryset``.

        The default ``DjangoObjectType.get_node`` returns ``None`` when
        ``get_queryset`` filters the row out.  That breaks non-nullable FK
        fields because GraphQL cannot coerce ``None`` into a concrete type.

        This override detects the "row exists but is hidden" case and returns
        a sentinel instance with ``pk=0`` and all other fields at their
        defaults — so the FK resolves without leaking private data.

        The sentinel preserves the hidden row's real FK IDs so that
        visible downstream objects resolve normally.  If a downstream
        target is also hidden, it produces its own sentinel — the chain
        is handled recursively by each type's ``get_node``.

        The Relay global ID encodes to ``<TypeName>:0`` (e.g.
        ``T2JqZWN0VHlwZU5vZGU6MA==``), signalling to clients that the
        relationship exists but the target is not accessible.
        """
        if id is None:
            return None

        # Sentinel chain: propagate when a parent sentinel's FK ID
        # could not be resolved (fallback value of 0).
        # int 0 from FK resolution, str "0" from Relay global ID decoding.
        if id == 0 or id == "0":
            return cls._make_sentinel()

        queryset = cls.get_queryset(cls._meta.model.objects, info)
        try:
            return queryset.get(pk=id)
        except cls._meta.model.DoesNotExist:
            if cls._meta.model.objects.filter(pk=id).exists():
                # The row exists but get_queryset hid it.  Return a
                # redacted sentinel so non-nullable FK fields don't break.
                logger.info(
                    "Sentinel returned for %s pk=%s — row hidden by get_queryset. "
                    "Downstream objects reachable only through this FK will also "
                    "appear as sentinels even if the user has direct access to them. "
                    "Use apply_cascade_permissions() in get_queryset to exclude "
                    "parent rows whose FK targets are hidden.",
                    cls.__name__,
                    id,
                )
                return cls._make_sentinel(source_pk=id)
            return None


_deny_value_cache: dict[tuple[type, str], Any] = {}


def _get_deny_value(model: type, field_name: str) -> Any:
    """Compute the value to return when a permission gate denies a field.

    Uses the Django model field's ``get_default()`` to derive a type-appropriate
    value automatically.  For ``DateTimeField`` and ``DateField`` the default is
    always set to epoch (1970-01-01) first — if the field has a real default
    (i.e. not ``auto_now`` / ``auto_now_add``), ``get_default()`` overwrites it.

    Returns ``None`` for fields that are nullable or not on the model
    (e.g. computed fields).

    Results are cached by ``(model, field_name)`` — the deny value for a given
    field never changes between users or sessions.
    """
    key = (model, field_name)
    if key in _deny_value_cache:
        return _deny_value_cache[key]

    try:
        model_field = model._meta.get_field(field_name)
    except Exception:
        _deny_value_cache[key] = None
        return None  # Computed field or unknown → None

    # Nullable fields can safely return None — GraphQL allows it.
    if model_field.null:
        _deny_value_cache[key] = None
        return None

    # Let Django's real default overwrite the epoch fallback.
    default = model_field.get_default()
    # Epoch fallback for non-nullable date/datetime fields (covers auto_now/
    # auto_now_add which report has_default=False but are non-nullable).
    if default is None:
        if isinstance(model_field, models.DateTimeField):
            default = _EPOCH_DATETIME
        elif isinstance(model_field, models.DateField):
            default = _EPOCH_DATE

    _deny_value_cache[key] = default
    return default


def _wrap_field_resolvers(node_cls: type, fields_class: type) -> None:
    """Wrap resolvers for fields managed by a ``FieldSet``.

    For each field in ``_managed_fields``, find the corresponding graphene
    field on the node type and wrap its resolver with the cascade:
    check → resolve → default.

    Also injects computed fields declared as graphene type attributes on
    the FieldSet (e.g. ``display_name = graphene.String()``) into the
    node type so they appear in the schema automatically.
    """
    managed = getattr(fields_class, "_managed_fields", set())
    computed = getattr(fields_class, "_computed_fields", {})
    if not managed and not computed:
        return

    meta_fields = getattr(node_cls._meta, "fields", {})

    # Inject computed fields into the node type's schema.
    for field_name, unmounted_type in computed.items():
        graphql_name = to_camel_case(field_name)
        if graphql_name not in meta_fields and field_name not in meta_fields:
            mounted = unmounted_type.mount_as(graphene.Field)
            meta_fields[graphql_name] = mounted

    for field_name in managed:
        # Graphene may store the field under camelCase or snake_case
        # depending on version — check both to be safe.
        graphql_name = to_camel_case(field_name)
        if graphql_name in meta_fields:
            graphene_field = meta_fields[graphql_name]
        elif field_name in meta_fields:
            graphene_field = meta_fields[field_name]
        else:
            logger.warning(
                "%s references field '%s' but it is not in %s's fields. "
                "The permission/resolve method will have no effect.",
                fields_class.__name__,
                field_name,
                node_cls.__name__,
            )
            continue

        # Capture the original resolver — this preserves graphene-django's
        # custom FK resolvers (which go through get_node) and the sentinel system.
        original_resolver = graphene_field.resolver

        # Pre-compute the deny value once at schema build time.
        model = getattr(getattr(fields_class, "Meta", None), "model", None)
        deny_value = _get_deny_value(model, field_name) if model else None

        def make_wrapper(
            fname: str,
            orig: Any,
            deny_val: Any,
        ) -> Any:
            def permission_checking_resolver(root: Any, info: Any, **kwargs: Any) -> Any:
                fieldset = fields_class(info)

                # Step 1: Permission gate — absolute.
                # Denied = denied.  resolve_ does NOT run.
                # The wrapper returns a type-appropriate default for
                # non-nullable fields (deny_val), or None for nullable.
                if not fieldset.check_field(fname):
                    return deny_val

                # Step 2: Custom resolver (runs if defined, check already passed)
                if fieldset.has_resolve_method(fname):
                    return fieldset.resolve_field(fname, root, info)

                # Step 3: Default resolver (no custom resolve defined)
                # This preserves graphene-django's FK/sentinel resolvers.
                if orig:
                    return orig(root, info, **kwargs)
                return getattr(root, fname, None)

            return permission_checking_resolver

        graphene_field.resolver = make_wrapper(field_name, original_resolver, deny_value)


# ---------------------------------------------------------------------------
# Converter override: upgrade sub-edge connection fields
# ---------------------------------------------------------------------------
# graphene-django's default converter creates DjangoFilterConnectionField for
# reverse relations (ManyToOneRel, ManyToManyField, ManyToManyRel).  We
# re-register the singledispatch converter so that when the *target* type is
# an AdvancedDjangoObjectType the connection field is an
# AdvancedDjangoFilterConnectionField instead — giving sub-edges the same
# tree-structured ``filter``, ``orderBy`` and ``search`` arguments that
# root-level queries enjoy.


@convert_django_field.register(models.ManyToManyField)
@convert_django_field.register(models.ManyToManyRel)
@convert_django_field.register(models.ManyToOneRel)
def _convert_field_to_list_or_connection(field: Any, registry: Any = None) -> Dynamic:
    model = field.related_model

    def dynamic_type() -> Any:
        _type = registry.get_type_for_model(model)
        if not _type:
            return

        if isinstance(field, models.ManyToManyField):
            description = get_django_field_description(field)
        else:
            description = get_django_field_description(field.field)

        if _type._meta.connection:
            if _type._meta.filter_fields or _type._meta.filterset_class:
                # Use AdvancedDjangoFilterConnectionField when the target is
                # an AdvancedDjangoObjectType; fall back to the standard
                # DjangoFilterConnectionField otherwise.
                if isinstance(_type, type) and issubclass(_type, AdvancedDjangoObjectType):
                    from .connection_field import AdvancedDjangoFilterConnectionField

                    return AdvancedDjangoFilterConnectionField(_type, required=True, description=description)

                from graphene_django.filter.fields import DjangoFilterConnectionField

                return DjangoFilterConnectionField(_type, required=True, description=description)

            return DjangoConnectionField(_type, required=True, description=description)

        return DjangoListField(_type, required=True, description=description)

    return Dynamic(dynamic_type)
