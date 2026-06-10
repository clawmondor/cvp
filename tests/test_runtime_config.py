"""Tests for AppSetting model and runtime_config service."""

from cvp.models_app_setting import AppSetting


def test_app_setting_model_importable_with_expected_columns():
    cols = {c.name for c in AppSetting.__table__.columns}
    assert cols == {"key", "value_json", "updated_at", "updated_by_user_id"}
