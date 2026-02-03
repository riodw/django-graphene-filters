"""Tests for the django_graphene_filters module."""

from django_graphene_filters import __version__


def test_version() -> None:
    """Test that the version number is correct."""
    assert __version__ == "0.1.1"
