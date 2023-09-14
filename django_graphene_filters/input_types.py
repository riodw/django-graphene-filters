"""InputObjectType classes for special lookups."""

from typing import Type, cast

import graphene

from .conf import settings


class SearchConfigInputType(graphene.InputObjectType):
    """Input type for the `SearchVector` or `SearchQuery` object config."""

    value = graphene.String(
        required=True,
        description="The configuration value for  `SearchVector` or `SearchQuery`",
    )
    is_field = graphene.Boolean(
        default_value=False,
        description="Flag to indicate if the value should be wrapped with the F object",
    )


class SearchVectorWeight(graphene.Enum):
    """Enum to represent the weight of a SearchVector object."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"


class SearchVectorInputType(graphene.InputObjectType):
    """Input type to create a SearchVector object."""

    fields = graphene.InputField(
        graphene.List(graphene.NonNull(graphene.String)),
        required=True,
        description="The field names to be used in the vector",
    )
    config = graphene.InputField(
        SearchConfigInputType, description="Configuration settings for the vector"
    )
    weight = graphene.InputField(
        SearchVectorWeight, description="The weight to be applied to the vector"
    )


class SearchQueryType(graphene.Enum):
    """Enum to represent the type of a SearchQuery object."""

    PLAIN = "plain"
    PHRASE = "phrase"
    RAW = "raw"
    WEBSEARCH = "websearch"


def create_search_query_input_type() -> Type[graphene.InputObjectType]:
    """
    Create and return an InputObjectType for a SearchQuery object.

    Returns:
        The InputObjectType class for the SearchQuery object.
    """
    # Define the attributes of the new class dynamically.
    attrs = {
        "__doc__": "Input type for creating a SearchQuery object.",
        "value": graphene.String(description="The search query value"),
        "config": graphene.InputField(
            SearchConfigInputType, description="Configuration settings for the query"
        ),
        settings.AND_KEY: graphene.InputField(
            graphene.List(
                graphene.NonNull(lambda: SearchQueryInputType)
            ),  # Type will be set after initialization
            description="AND logical operator field",
        ),
        settings.OR_KEY: graphene.InputField(
            graphene.List(
                graphene.NonNull(lambda: SearchQueryInputType)
            ),  # Type will be set after initialization
            description="OR logical operator field",
        ),
        settings.NOT_KEY: graphene.InputField(
            graphene.List(
                graphene.NonNull(lambda: SearchQueryInputType)
            ),  # Type will be set after initialization
            description="NOT logical operator field",
        ),
    }
    search_query_input_type = cast(
        Type[graphene.InputObjectType],
        type(
            "SearchQueryInputType",
            (graphene.InputObjectType,),
            attrs,
        ),
    )
    return search_query_input_type


# Initialize the SearchQueryInputType
SearchQueryInputType = create_search_query_input_type()


class SearchQueryFilterInputType(graphene.InputObjectType):
    """Input type for the full text search using the `SearchVector` and `SearchQuery` objects."""

    vector = graphene.InputField(
        SearchVectorInputType,
        required=True,
        description="The SearchVector to be used",
    )
    query = graphene.InputField(
        SearchQueryInputType,
        required=True,
        description="The SearchQuery to be used",
    )


class FloatLookupsInputType(graphene.InputObjectType):
    """Input type for handling floating-point number-based lookups."""

    exact = graphene.Float(description="Exact match value")
    gt = graphene.Float(description="Greater than value")
    gte = graphene.Float(description="Greater than or equal to value")
    lt = graphene.Float(description="Less than value")
    lte = graphene.Float(description="Less than or equal to value")


class SearchRankWeightsInputType(graphene.InputObjectType):
    """`SearchRank` object weights.

    Input type for specifying the weights for SearchRank objects.

    Default values are set according to Django documentation.
    https://docs.djangoproject.com/en/3.2/ref/contrib/postgres/search/#weighting-queries
    """

    D = graphene.Float(default_value=0.1, description="Weight for D letter")
    C = graphene.Float(default_value=0.2, description="Weight for C letter")
    B = graphene.Float(default_value=0.4, description="Weight for B letter")
    A = graphene.Float(default_value=1.0, description="Weight for A letter")


class SearchRankFilterInputType(graphene.InputObjectType):
    """Input type for the full-text search using the `SearchRank` objects."""

    vector = graphene.InputField(
        SearchVectorInputType,
        required=True,
        description="Vector used for ranking",
    )
    query = graphene.InputField(
        SearchQueryInputType,
        required=True,
        description="Query used for ranking",
    )
    lookups = graphene.InputField(
        FloatLookupsInputType,
        required=True,
        description="Lookup options for floating-point values",
    )
    weights = graphene.InputField(
        SearchRankWeightsInputType,
        description="Search rank weights",
    )
    cover_density = graphene.Boolean(
        default_value=False,
        description="Whether to include coverage density in ranking",
    )
    normalization = graphene.Int(description="Search normalization used in ranking")


class TrigramSearchKind(graphene.Enum):
    """Enum type to specify the kind of trigram-based search: similarity or distance."""

    SIMILARITY = "similarity"
    DISTANCE = "distance"


class TrigramFilterInputType(graphene.InputObjectType):
    """Input type for the full text search using similarity or distance of trigram."""

    kind = graphene.InputField(
        TrigramSearchKind,
        default_value=TrigramSearchKind.SIMILARITY,
        description="Type of trigram search",
    )
    lookups = graphene.InputField(
        FloatLookupsInputType,
        required=True,
        description="Available lookups",
    )
    value = graphene.String(
        required=True,
        description="Value used in trigram search",
    )
