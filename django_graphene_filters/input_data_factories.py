"""Functions for converting tree data into data suitable for the FilterSet."""

from typing import Any, Dict, List, Optional, Type, Union

# Django imports
from django.contrib.postgres.search import (
    SearchQuery,
    SearchRank,
    SearchVector,
    TrigramDistance,
    TrigramSimilarity,
)
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

DATA_FACTORIES = {}  # Define this dict based on your actual factories


def tree_input_type_to_data(
    filterset_class: Type[AdvancedFilterSet],
    tree_input_type: InputObjectTypeContainer,
    prefix: str = "",
) -> Dict[str, Any]:
    """Convert a tree_input_type to a FilterSet data."""
    result: Dict[str, Any] = {}
    for key, value in tree_input_type.items():
        # Handling logical operations on the filter set
        if key in ("and", "or"):
            result[key] = [
                tree_input_type_to_data(filterset_class, subtree) for subtree in value
            ]
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


def create_data(
    key: str, value: Any, filterset_class: Type[AdvancedFilterSet]
) -> Dict[str, Any]:
    """Create data from a key and a value based on factory methods."""
    for factory_key, factory in DATA_FACTORIES.items():
        if factory_key in key:
            return factory(value, key, filterset_class)
    # If the value is an InputObjectTypeContainer, convert it into a suitable FilterSet data
    if isinstance(value, InputObjectTypeContainer):
        return tree_input_type_to_data(filterset_class, value, key)
    else:
        return {key: value}


def create_search_query_data(
    input_type: SearchQueryFilterInputType,
    key: str,
    filterset_class: Type[AdvancedFilterSet],
) -> Dict[str, SearchQueryFilter.Value]:
    """
    Create a dictionary suitable for the `SearchQueryFilter` class.

    Parameters:
    - input_type (SearchQueryFilterInputType): Input data to create the search query
    - key (str): The field key on which the search query will be applied
    - filterset_class (Type[AdvancedFilterSet]): The filterset class that will be using this filter

    Returns:
    - A dictionary containing the search query filter values
    """
    # Create the SearchVector and SearchQuery from the input_type
    annotation_value = create_search_vector(input_type.vector, filterset_class)
    search_value = create_search_query(input_type.query)

    return {
        key: SearchQueryFilter.Value(
            annotation_value=annotation_value,
            search_value=search_value,
        ),
    }


def create_search_rank_data(
    input_type: Union[SearchRankFilterInputType, InputObjectTypeContainer],
    key: str,
    filterset_class: Type[AdvancedFilterSet],
) -> Dict[str, SearchRankFilter.Value]:
    """
    Create a dictionary suitable for the `SearchRankFilter` class.

    Parameters:
    - input_type (Union[SearchRankFilterInputType, InputObjectTypeContainer]): Input data for
        creating the search rank.
    - key (str): The field key on which the search rank will be applied.
    - filterset_class (Type[AdvancedFilterSet]): The filterset class that will be using this filter.

    Returns:
    - A dictionary containing the search rank filter values.
    """
    # Initialize the result dictionary
    rank_data = {}

    # Iterate through each lookup in the input_type.lookups dictionary
    for lookup, value in input_type.lookups.items():
        # Create the SearchRank data
        search_rank_data = {
            "vector": create_search_vector(input_type.vector, filterset_class),
            "query": create_search_query(input_type.query),
            "cover_density": input_type.cover_density,
        }

        # If weights are provided, add them to the SearchRank data
        weights = input_type.get("weights")
        if weights:
            search_rank_data["weights"] = create_search_rank_weights(weights)

        # If normalization is provided, add it to the SearchRank data
        normalization = input_type.get("normalization")
        if normalization:
            search_rank_data["normalization"] = normalization

        # Create the complete key for this specific lookup
        complete_key = (key + LOOKUP_SEP + lookup).replace(
            LOOKUP_SEP + django_settings.DEFAULT_LOOKUP_EXPR, ""
        )
        # Add the SearchRank value to the result dictionary
        rank_data[complete_key] = SearchRankFilter.Value(
            annotation_value=SearchRank(**search_rank_data),
            search_value=value,
        )

    return rank_data


def create_trigram_data(
    input_type: TrigramFilterInputType, key: str, *args
) -> Dict[str, TrigramFilter.Value]:
    """Create a data for the `TrigramFilter` class."""
    trigram_data = {}
    if input_type.kind == TrigramSearchKind.SIMILARITY:
        trigram_class = TrigramSimilarity
    else:
        trigram_class = TrigramDistance
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
    input_type: Union[SearchVectorInputType, InputObjectTypeContainer],
    filterset_class: Type[AdvancedFilterSet],
) -> SearchVector:
    """
    Create an object of the `SearchVector` class based on the provided input_type and filterset_class.

    Args:
        input_type (Union[SearchVectorInputType, InputObjectTypeContainer]): The input data
            for the search vector.
        filterset_class (Type[AdvancedFilterSet]): The FilterSet class for further validation.

    Returns:
        SearchVector: An instance of Django's SearchVector class.
    """
    # Validate the fields in the input against the filterset class
    validate_search_vector_fields(filterset_class, input_type.fields)

    # Initialize a dictionary to hold the keyword arguments for SearchVector
    search_vector_data = {}

    # Check if the config is provided in input_type and create the search config accordingly
    config = input_type.get("config")
    if config:
        search_vector_data["config"] = create_search_config(config)

    # Check if the weight is provided in input_type and add it to search_vector_data
    weight = input_type.get("weight")
    if weight:
        search_vector_data["weight"] = weight.value

    # Create and return a SearchVector instance
    return SearchVector(*input_type.fields, **search_vector_data)


def create_search_query(
    input_type: Union[SearchQueryInputType, InputObjectTypeContainer],
) -> Optional[SearchQuery]:
    """
    Create an object of the `SearchQuery` class based on the provided input_type.

    Args:
        input_type (Union[SearchQueryInputType, InputObjectTypeContainer]): The input
            data for creating the search query.

    Returns:
        Optional[SearchQuery]: An instance of Django's SearchQuery class,
        or None if no valid query could be constructed.
    """
    # Validate the incoming search query
    validate_search_query(input_type)

    # Initialize the search query
    search_query = None

    # Get the base query value and optional configuration
    value = input_type.get("value")
    if value:
        config = input_type.get("config")
        search_query = SearchQuery(
            input_type.value,
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
    valid_queries = (
        q
        for q in (and_search_query, or_search_query, not_search_query)
        if q is not None
    )
    for valid_query in valid_queries:
        search_query = search_query & valid_query if search_query else valid_query
    return search_query


def create_search_config(input_type: SearchConfigInputType) -> Union[str, models.F]:
    """Create a `SearchVector` or `SearchQuery` object config."""
    return models.F(input_type.value) if input_type.is_field else input_type.value


def create_search_rank_weights(input_type: SearchRankWeightsInputType) -> List[float]:
    """Create a search rank weights list."""
    return [input_type.D, input_type.C, input_type.B, input_type.A]


def validate_search_vector_fields(
    filterset_class: Type[AdvancedFilterSet],
    fields: List[str],
) -> None:
    """Validate that fields is included in full text search fields."""
    full_text_search_fields = filterset_class.get_full_text_search_fields()
    for field in fields:
        if field not in full_text_search_fields:
            raise ValidationError(
                f"The `{field}` field is not included in full text search fields"
            )


def validate_search_query(
    input_type: Union[SearchQueryInputType, InputObjectTypeContainer],
) -> None:
    """Validate that search query contains at least one required field."""
    if all(
        [
            "value" not in input_type,
            settings.AND_KEY not in input_type,
            settings.OR_KEY not in input_type,
            settings.NOT_KEY not in input_type,
        ]
    ):
        raise ValidationError(
            "The search query must contains at least one required field "
            f"such as `value`, `{settings.AND_KEY}`, `{settings.OR_KEY}`, `{settings.NOT_KEY}`.",
        )


DATA_FACTORIES = {
    SearchQueryFilter.postfix: create_search_query_data,
    SearchRankFilter.postfix: create_search_rank_data,
    TrigramFilter.postfix: create_trigram_data,
}
