from django_graphene_filters.conf import settings, Settings, reload_settings, DJANGO_SETTINGS_KEY
from django.test import override_settings
import pytest
from unittest.mock import MagicMock, patch

def test_settings_invalid_attribute():
    with pytest.raises(AttributeError):
        _ = settings.INVALID_SETTING

def test_settings_user_setting():
    # settings.user_settings looks at django_settings.DJANGO_GRAPHENE_FILTERS
    with override_settings(DJANGO_GRAPHENE_FILTERS={"FILTER_KEY": "my_filter"}):
        # We need to force reload or use a new Settings object
        s = Settings()
        assert s.FILTER_KEY == "my_filter"

def test_reload_settings():
    from django_graphene_filters import conf
    old_settings = conf.settings
    try:
        with patch("django_graphene_filters.conf.Settings") as mock_settings_class:
            reload_settings(DJANGO_SETTINGS_KEY, {"FILTER_KEY": "new"})
            mock_settings_class.assert_called_with({"FILTER_KEY": "new"})
    finally:
        conf.settings = old_settings

def test_check_pg_trigram_extension():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [1]
    
    with patch("django.db.connection.cursor", return_value=MagicMock(__enter__=lambda s: mock_cursor)):
        from django_graphene_filters.conf import check_pg_trigram_extension
        res = check_pg_trigram_extension()
        assert res is True

def test_check_pg_trigram_extension_fail():
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = [0]
    
    with patch("django.db.connection.cursor", return_value=MagicMock(__enter__=lambda s: mock_cursor)):
        from django_graphene_filters.conf import check_pg_trigram_extension
        res = check_pg_trigram_extension()
        assert res is False
