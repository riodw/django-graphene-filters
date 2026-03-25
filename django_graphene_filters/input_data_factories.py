"""Functions for converting tree data into data suitable for the FilterSet."""

from typing import Any

# Django imports
try:
    from django.contrib.postgres.search import (
        SearchQuery,
        SearchRank,
        SearchVector,
        TrigramDistance,
        TrigramSimilarity,
    )
except ImportError:  # pragma: no cover — psycopg2 / postgres not installed
    SearchQuery = None
    SearchRank = None
    SearchVector = None
    TrigramDistance = None
    TrigramSimilarity = None
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.constants import LOOKUP_SEP
from django_filters.conf import settings as django_settings
from graphene.types.inputobjecttype import InputObjectTypeContainer

# Local imports
from .conf import settings
from .filters import (
    SearchQueryFilter,
    SearchRankFilter,
    TrigramFilter,
)
from .filterset import AdvancedFilterSet
from .input_types import (
    SearchConfigInputType,
    SearchQueryFilterInputType,
    SearchQueryInputType,
    SearchRankFilterInputType,
    SearchRankWeightsInputType,
    SearchVectorInputType,
    TrigramFilterInputType,
    TrigramSearchKind,
)


def tree_input_type_to_data(
    filterset_class: type[AdvancedFilterSet],
    tree_input_type: InputObjectTypeContainer,
    prefix: str = "",
) -> dict[str, Any]:
    """Convert a tree_input_type to a FilterSet data."""
    result: dict[str, Any] = {}
    for key, value in tree_input_type.items():
        # Handling logical operations on the filter set
        if key in ("and", "or"):
            result[key] = [tree_input_type_to_data(filterset_class, subtree) for subtree in value]
        elif key == "not":
            result[key] = tree_input_type_to_data(filterset_class, value)
        else:
            # Translate remaining key-value pairs into data suitable for the FilterSet
            result.update(
                create_data(
                    (prefix + LOOKUP_SEP + key if prefix else key).replace(
                        LOOKUP_SEP + django_settings.DEFAULT_LOOKUP_EXPR,
                        "",
                    ),
                    value,
                    filterset_class,
                ),
            )
    return result


def create_data(key: str, value: Any, filterset_class: type[AdvancedFilterSet]) -> dict[str, Any]:
    """Create data from a key and value, dispatching to special factories when matched."""
    for factory_key, factory in DATA_FACTORIES.items():
        if factory_key in key:
            return factory(value, key, filterset_class)
    # Nested InputObjectType → recurse into the subtree
    if isinstance(value, InputObjectTypeContainer):
        return tree_input_type_to_data(filterset_class, value, key)
    return {key: value}


def create_search_query_data(
    input_type: SearchQueryFilterInputType,
    key: str,
    filterset_class: type[AdvancedFilterSet],
) -> dict[str, SearchQueryFilter.Value]:
    """Create a dictionary suitable for the ``SearchQueryFilter`` class."""
    annotation_value = create_search_vector(input_type.vector, filterset_class)
    search_value = create_search_query(input_type.query)

    return {
        key: SearchQueryFilter.Value(
            annotation_value=annotation_value,
            search_value=search_value,
        ),
    }


def create_search_rank_data(
    input_type: SearchRankFilterInputType | InputObjectTypeContainer,
    key: str,
    filterset_class: type[AdvancedFilterSet],
) -> dict[str, SearchRankFilter.Value]:
    """Create a dictionary suitable for the ``SearchRankFilter`` class."""
    rank_data = {}

    for lookup, value in input_type.lookups.items():
        search_rank_data = {
            "vector": create_search_vector(input_type.vector, filterset_class),
            "query": create_search_query(input_type.query),
            "cover_density": input_type.cover_density,
        }

        weights = input_type.get("weights")
        if weights:
            search_rank_data["weights"] = create_search_rank_weights(weights)

        normalization = input_type.get("normalization")
        if normalization:
            search_rank_data["normalization"] = normalization

        complete_key = (key + LOOKUP_SEP + lookup).replace(
            LOOKUP_SEP + django_settings.DEFAULT_LOOKUP_EXPR, ""
        )
        rank_data[complete_key] = SearchRankFilter.Value(
            annotation_value=SearchRank(**search_rank_data),
            search_value=value,
        )

    return rank_data


def create_trigram_data(
    input_type: TrigramFilterInputType, key: str, _filterset_class: type[AdvancedFilterSet] | None = None
) -> dict[str, TrigramFilter.Value]:
    """Create data for the ``TrigramFilter`` class."""
    trigram_data = {}
    trigram_class = TrigramSimilarity if input_type.kind == TrigramSearchKind.SIMILARITY else TrigramDistance
    for lookup, value in input_type.lookups.items():
        k = (key + LOOKUP_SEP + lookup).replace(
            LOOKUP_SEP + django_settings.DEFAULT_LOOKUP_EXPR,
            "",
        )
        trigram_data[k] = TrigramFilter.Value(
            annotation_value=trigram_class(
                LOOKUP_SEP.join(key.split(LOOKUP_SEP)[:-1]),
                input_type.value,
            ),
            search_value=value,
        )
    return trigram_data


def create_search_vector(
    input_type: SearchVectorInputType | InputObjectTypeContainer,
    filterset_class: type[AdvancedFilterSet],
) -> SearchVector:
    """Create a ``SearchVector`` from the given input type."""
    validate_search_vector_fields(filterset_class, input_type.fields)

    search_vector_data = {}

    config = input_type.get("config")
    if config:
        search_vector_data["config"] = create_search_config(config)

    weight = input_type.get("weight")
    if weight:
        search_vector_data["weight"] = weight.value

    return SearchVector(*input_type.fields, **search_vector_data)


def create_search_query(
    input_type: SearchQueryInputType | InputObjectTypeContainer,
) -> SearchQuery | None:
    """Create a ``SearchQuery`` from the given input type, or ``None``."""
    validate_search_query(input_type)

    search_query = None

    value = input_type.get("value")
    if value:
        config = input_type.get("config")
        search_query = SearchQuery(
            value,
            config=create_search_config(config) if config else None,
        )

    and_search_query = None
    for and_input_type in input_type.get(settings.AND_KEY, []):
        if and_search_query is None:
            and_search_query = create_search_query(and_input_type)
        else:
            and_search_query = and_search_query & create_search_query(and_input_type)
    or_search_query = None
    for or_input_type in input_type.get(settings.OR_KEY, []):
        if or_search_query is None:
            or_search_query = create_search_query(or_input_type)
        else:
            or_search_query = or_search_query | create_search_query(or_input_type)
    not_input_type = input_type.get(settings.NOT_KEY)
    not_search_query = create_search_query(not_input_type) if not_input_type else None
    valid_queries = (q for q in (and_search_query, or_search_query, not_search_query) if q is not None)
    for valid_query in valid_queries:
        search_query = search_query & valid_query if search_query else valid_query
    return search_query


def create_search_config(input_type: SearchConfigInputType) -> str | models.F:
    """Create a `SearchVector` or `SearchQuery` object config."""
    return models.F(input_type.value) if input_type.is_field else input_type.value


def create_search_rank_weights(input_type: SearchRankWeightsInputType) -> list[float]:
    """Create a search rank weights list."""
    return [input_type.D, input_type.C, input_type.B, input_type.A]


def validate_search_vector_fields(
    filterset_class: type[AdvancedFilterSet],
    fields: list[str],
) -> None:
    """Validate that all fields are declared as full-text search fields."""
    full_text_search_fields = filterset_class.get_full_text_search_fields()
    for field in fields:
        if field not in full_text_search_fields:
            raise ValidationError(f"The `{field}` field is not included in full text search fields")


def validate_search_query(
    input_type: SearchQueryInputType | InputObjectTypeContainer,
) -> None:
    """Validate that the search query contains at least one required field."""
    if all(key not in input_type for key in ("value", settings.AND_KEY, settings.OR_KEY, settings.NOT_KEY)):
        raise ValidationError(
            "The search query must contain at least one required field "
            f"such as `value`, `{settings.AND_KEY}`, `{settings.OR_KEY}`, `{settings.NOT_KEY}`.",
        )


DATA_FACTORIES = {
    SearchQueryFilter.postfix: create_search_query_data,
    SearchRankFilter.postfix: create_search_rank_data,
    TrigramFilter.postfix: create_trigram_data,
}
