"""Tests for cache warming module."""
import pytest
from dataclasses import dataclass

from lazy_config import (
    prewarm_config_analysis_cache,
    prewarm_callable_analysis_cache,
)


def test_prewarm_config_analysis_cache():
    """Test prewarming config analysis cache."""
    @dataclass
    class Config1:
        value: str = "test1"

    @dataclass
    class Config2:
        value: str = "test2"

    # Should not raise an error
    prewarm_config_analysis_cache([Config1, Config2])


def test_prewarm_callable_analysis_cache():
    """Test prewarming callable analysis cache."""
    def sample_function():
        return "test"

    class SampleClass:
        def method(self):
            return "test"

    # Should not raise an error
    prewarm_callable_analysis_cache([sample_function, SampleClass.method])


def test_prewarm_empty_list():
    """Test prewarming with empty list."""
    # Should handle empty lists gracefully
    prewarm_config_analysis_cache([])
    prewarm_callable_analysis_cache([])


def test_prewarm_with_none():
    """Test that cache warming handles edge cases."""
    @dataclass
    class MyConfig:
        value: str = None

    # Should not raise error even with None default
    prewarm_config_analysis_cache([MyConfig])
