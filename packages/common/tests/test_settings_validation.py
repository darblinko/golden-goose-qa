"""Boundary validation on AppSettings that has no better home elsewhere."""

import pytest
from gg_common.settings import AppSettings
from pydantic import ValidationError


def test_root_path_defaults_to_empty():
    assert AppSettings().api_root_path == ""


def test_root_path_strips_trailing_slash():
    assert AppSettings(api_root_path="/api/").api_root_path == "/api"
    # A bare "/" carries no real prefix and normalizes to empty.
    assert AppSettings(api_root_path="/").api_root_path == ""


def test_root_path_without_leading_slash_is_rejected():
    with pytest.raises(ValidationError):
        AppSettings(api_root_path="api")
