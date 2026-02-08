from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.db import models

from django_graphene_filters.filters import (
    SearchQueryFilter,
)
from django_graphene_filters.input_data_factories import (
    create_data,
    create_search_config,
    create_search_query,
    create_search_query_data,
    create_search_rank_data,
    create_search_rank_weights,
    create_search_vector,
    create_trigram_data,
    tree_input_type_to_data,
    validate_search_query,
    validate_search_vector_fields,
)
from django_graphene_filters.input_types import TrigramSearchKind


class MockFilterSet:
    @classmethod
    def get_full_text_search_fields(cls):
        return ["name", "description"]


@pytest.fixture
def filterset_class():
    return MockFilterSet


def test_tree_input_type_to_data_logic(filterset_class):
    # Test 'and', 'or', 'not' logic
    tree = {
        "and": [{"name": "foo"}],
        "or": [{"name": "bar"}],
        "not": {"name": "baz"},
    }

    # Mocking tree_input_type which is usually a dict-like from Graphene
    class MockInput(dict):
        def items(self):
            return super().items()

    input_data = MockInput(tree)

    with patch("django_graphene_filters.input_data_factories.create_data") as mock_create:
        mock_create.side_effect = lambda k, v, fs: {k: v}
        result = tree_input_type_to_data(filterset_class, input_data)

        assert "and" in result
        assert "or" in result
        assert "not" in result
        assert result["and"] == [{"name": "foo"}]
        assert result["or"] == [{"name": "bar"}]
        assert result["not"] == {"name": "baz"}


def test_create_data_with_factory(filterset_class):
    with patch("django_graphene_filters.input_data_factories.DATA_FACTORIES") as mock_factories:
        mock_factory = MagicMock(return_value={"custom": "data"})
        mock_factories.items.return_value = [("_search", mock_factory)]

        result = create_data("name_search", "value", filterset_class)
        assert result == {"custom": "data"}
        mock_factory.assert_called_once_with("value", "name_search", filterset_class)


def test_create_search_query_data(filterset_class):
    input_type = MagicMock()
    input_type.vector = MagicMock()
    input_type.query = MagicMock()

    with patch("django_graphene_filters.input_data_factories.create_search_vector") as mock_vector, patch(
        "django_graphene_filters.input_data_factories.create_search_query"
    ) as mock_query:

        mock_vector.return_value = "mock_vector"
        mock_query.return_value = "mock_query"

        result = create_search_query_data(input_type, "my_search", filterset_class)

        assert "my_search" in result
        assert isinstance(result["my_search"], SearchQueryFilter.Value)
        assert result["my_search"].annotation_value == "mock_vector"
        assert result["my_search"].search_value == "mock_query"


def test_create_search_rank_data(filterset_class):
    input_type = MagicMock()
    input_type.lookups = {"gt": 0.5}
    input_type.vector = MagicMock()
    input_type.query = MagicMock()
    input_type.cover_density = True
    input_type.get.side_effect = lambda k: {
        "weights": "mock_weights",
        "normalization": 1,
    }.get(k)

    with patch("django_graphene_filters.input_data_factories.create_search_vector") as mock_vector, patch(
        "django_graphene_filters.input_data_factories.create_search_query"
    ) as mock_query, patch(
        "django_graphene_filters.input_data_factories.create_search_rank_weights"
    ) as mock_weights, patch(
        "django_graphene_filters.input_data_factories.SearchRank"
    ) as mock_rank:

        mock_vector.return_value = "v"
        mock_query.return_value = "q"
        mock_weights.return_value = [0.1, 0.2, 0.3, 0.4]
        mock_rank.return_value = "RANK_OBJ"

        result = create_search_rank_data(input_type, "my_rank", filterset_class)

        assert "my_rank__gt" in result
        assert result["my_rank__gt"].annotation_value == "RANK_OBJ"
        assert result["my_rank__gt"].search_value == 0.5


def test_create_trigram_data():
    input_type = MagicMock()
    input_type.kind = TrigramSearchKind.SIMILARITY
    input_type.lookups = {"gt": 0.3}
    input_type.value = "test"

    with patch("django_graphene_filters.input_data_factories.TrigramSimilarity") as mock_sim:
        mock_sim.return_value = "SIM_OBJ"
        result = create_trigram_data(input_type, "field__trigram")

        assert "field__trigram__gt" in result
        assert result["field__trigram__gt"].annotation_value == "SIM_OBJ"
        assert result["field__trigram__gt"].search_value == 0.3


def test_create_trigram_data_distance():
    input_type = MagicMock()
    input_type.kind = TrigramSearchKind.DISTANCE
    input_type.lookups = {"lt": 0.7}
    input_type.value = "test"

    with patch("django_graphene_filters.input_data_factories.TrigramDistance") as mock_dist:
        mock_dist.return_value = "DIST_OBJ"
        result = create_trigram_data(input_type, "field__trigram")

        assert "field__trigram__lt" in result
        assert result["field__trigram__lt"].annotation_value == "DIST_OBJ"


def test_create_search_vector(filterset_class):
    input_type = MagicMock()
    input_type.fields = ["name"]
    input_type.get.side_effect = lambda k: {
        "config": "english",
        "weight": MagicMock(value="A"),
    }.get(k)

    with patch("django_graphene_filters.input_data_factories.validate_search_vector_fields"), patch(
        "django_graphene_filters.input_data_factories.create_search_config"
    ) as mock_config, patch("django_graphene_filters.input_data_factories.SearchVector") as mock_vector:

        mock_config.return_value = "english_config"
        mock_vector.return_value = "VECTOR_OBJ"

        res = create_search_vector(input_type, filterset_class)
        assert res == "VECTOR_OBJ"
        mock_vector.assert_called_once_with("name", config="english_config", weight="A")


def test_create_search_query():
    input_type = MagicMock()
    input_type.get.side_effect = lambda k, default=None: {
        "value": "search term",
        "config": "english",
        "and": [],
        "or": [],
        "not": None,
    }.get(k, default)
    input_type.value = "search term"

    with patch("django_graphene_filters.input_data_factories.validate_search_query"), patch(
        "django_graphene_filters.input_data_factories.create_search_config"
    ) as mock_config, patch("django_graphene_filters.input_data_factories.SearchQuery") as mock_query:

        mock_config.return_value = "english_config"
        mock_query.return_value = MagicMock()

        res = create_search_query(input_type)
        assert res is not None
        mock_query.assert_called_once_with("search term", config="english_config")


def test_create_search_query_complex():
    input_term = MagicMock()
    input_term.get.side_effect = lambda k, default=None: {"value": "term"}.get(k, default)
    input_term.value = "term"

    input_and = MagicMock()
    input_and.get.side_effect = lambda k, default=None: {"and": [input_term]}.get(k, default)

    with patch("django_graphene_filters.input_data_factories.validate_search_query"), patch(
        "django_graphene_filters.input_data_factories.SearchQuery"
    ) as mock_query:

        q1 = MagicMock()
        mock_query.return_value = q1

        res = create_search_query(input_and)
        assert res == q1


def test_create_search_config():
    input_type = MagicMock()
    input_type.value = "english"
    input_type.is_field = False
    assert create_search_config(input_type) == "english"

    input_type.is_field = True
    input_type.value = "language_field"
    res = create_search_config(input_type)
    assert isinstance(res, models.F)
    assert res.name == "language_field"


def test_create_search_rank_weights():
    input_type = MagicMock()
    input_type.A = 1.0
    input_type.B = 0.4
    input_type.C = 0.2
    input_type.D = 0.1
    assert create_search_rank_weights(input_type) == [0.1, 0.2, 0.4, 1.0]


def test_create_data_input_object_type(filterset_class):
    from graphene.types.inputobjecttype import InputObjectTypeContainer

    value = MagicMock(spec=InputObjectTypeContainer)

    with patch("django_graphene_filters.input_data_factories.tree_input_type_to_data") as mock_tree:
        mock_tree.return_value = {"tree": "data"}
        res = create_data("my_key", value, filterset_class)
        assert res == {"tree": "data"}
        mock_tree.assert_called_once_with(filterset_class, value, "my_key")


def test_create_data_simple(filterset_class):
    res = create_data("my_key", "simple_value", filterset_class)
    assert res == {"my_key": "simple_value"}


def test_create_search_query_complex_operations():
    # Test AND, OR, NOT operations in SearchQuery
    from django_graphene_filters.conf import settings as local_settings

    t1 = MagicMock()
    t1.get.side_effect = lambda k, d=None: {"value": "term1"}.get(k, d)
    t1.value = "term1"

    t2 = MagicMock()
    t2.get.side_effect = lambda k, d=None: {"value": "term2"}.get(k, d)
    t2.value = "term2"

    input_complex = MagicMock()

    def get_complex(k, d=None):
        if k == local_settings.AND_KEY:
            return [t1, t2]
        if k == local_settings.OR_KEY:
            return [t1, t2]
        if k == local_settings.NOT_KEY:
            return t1

    with patch("django_graphene_filters.input_data_factories.validate_search_query"), patch(
        "django_graphene_filters.input_data_factories.SearchQuery"
    ) as mock_query:

        q1 = MagicMock()
        q1.__and__.return_value = q1
        q1.__or__.return_value = q1
        mock_query.return_value = q1

        data = {
            local_settings.AND_KEY: [{"value": "term1"}, {"value": "term2"}],
            local_settings.OR_KEY: [{"value": "term3"}, {"value": "term4"}],
            local_settings.NOT_KEY: {"value": "term5"},
        }
        create_search_query(data)
        # 5 leaves = 5 calls to SearchQuery
        assert mock_query.call_count == 5


def test_validate_search_vector_fields_success(filterset_class):
    # Should not raise
    validate_search_vector_fields(filterset_class, ["name"])


def test_validate_search_vector_fields_fail(filterset_class):
    with pytest.raises(ValidationError):
        validate_search_vector_fields(filterset_class, ["invalid_field"])


def test_validate_search_query_fail():
    with pytest.raises(ValidationError):
        validate_search_query({})
