"""Shared types and constants for the aggregate system."""

import graphene


class UniqueValueType(graphene.ObjectType):
    """A unique value and its occurrence count."""

    value = graphene.String(description="The distinct value (as string)")
    count = graphene.Int(description="Number of occurrences")


# ---------------------------------------------------------------------------
# Field category classification for Django model fields
# ---------------------------------------------------------------------------

FIELD_CATEGORIES: dict[str, str] = {
    # text
    "CharField": "text",
    "TextField": "text",
    "SlugField": "text",
    "EmailField": "text",
    "URLField": "text",
    "UUIDField": "text",
    "FilePathField": "text",
    "IPAddressField": "text",
    "GenericIPAddressField": "text",
    # numeric
    "IntegerField": "numeric",
    "SmallIntegerField": "numeric",
    "BigIntegerField": "numeric",
    "PositiveIntegerField": "numeric",
    "PositiveSmallIntegerField": "numeric",
    "PositiveBigIntegerField": "numeric",
    "FloatField": "numeric",
    "DecimalField": "numeric",
    "AutoField": "numeric",
    "BigAutoField": "numeric",
    "SmallAutoField": "numeric",
    # datetime (separate categories for correct GraphQL scalar types)
    "DateTimeField": "datetime",
    "DateField": "date",
    "TimeField": "time",
    "DurationField": "duration",
    # boolean
    "BooleanField": "boolean",
    "NullBooleanField": "boolean",
}


# ---------------------------------------------------------------------------
# Mapping from stat names to graphene return types, per field category.
# Used by AggregateArgumentsFactory to generate the schema.
# ---------------------------------------------------------------------------

STAT_TYPES: dict[str, dict[str, type | graphene.List]] = {
    "text": {
        "count": graphene.Int,
        "min": graphene.String,
        "max": graphene.String,
        "mode": graphene.String,
        "uniques": graphene.List(UniqueValueType),
    },
    "numeric": {
        "count": graphene.Int,
        "min": graphene.Float,
        "max": graphene.Float,
        "sum": graphene.Float,
        "mean": graphene.Float,
        "median": graphene.Float,
        "mode": graphene.Float,
        "stdev": graphene.Float,
        "variance": graphene.Float,
        "uniques": graphene.List(UniqueValueType),
    },
    "datetime": {
        "count": graphene.Int,
        "min": graphene.DateTime,
        "max": graphene.DateTime,
    },
    "date": {
        "count": graphene.Int,
        "min": graphene.Date,
        "max": graphene.Date,
    },
    "time": {
        "count": graphene.Int,
        "min": graphene.Time,
        "max": graphene.Time,
    },
    "duration": {
        "count": graphene.Int,
        "min": graphene.Float,  # timedelta as total seconds
        "max": graphene.Float,
    },
    "boolean": {
        "count": graphene.Int,
        "true_count": graphene.Int,
        "false_count": graphene.Int,
    },
}

# Which stats are valid for each category (used for metaclass validation):
VALID_STATS: dict[str, set[str]] = {category: set(stats.keys()) for category, stats in STAT_TYPES.items()}
