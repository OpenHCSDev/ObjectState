"""Tests for config module."""
import pytest
from dataclasses import dataclass

from lazy_config import set_base_config_type, get_base_config_type


def test_set_and_get_base_config_type():
    """Test setting and getting base config type."""
    @dataclass
    class MyConfig:
        value: str = "test"

    set_base_config_type(MyConfig)
    assert get_base_config_type() == MyConfig


def test_get_base_config_type_not_set():
    """Test getting base config type when not set."""
    with pytest.raises(RuntimeError, match="Base config type not set"):
        get_base_config_type()


def test_set_base_config_type_override():
    """Test that setting base config type can override previous value."""
    @dataclass
    class Config1:
        value: str = "test1"

    @dataclass
    class Config2:
        value: str = "test2"

    set_base_config_type(Config1)
    assert get_base_config_type() == Config1

    set_base_config_type(Config2)
    assert get_base_config_type() == Config2
