"""Tests for cache warming module.

NOTE: Cache warming functionality requires openhcs which is NOT part of
the core hieraconf library. These tests are skipped in standalone usage.
"""

from dataclasses import dataclass

import pytest

from hieraconf import (
    prewarm_callable_analysis_cache,
    prewarm_config_analysis_cache,
)

# Cache warming requires openhcs - skip these tests for standalone hieraconf
pytestmark = pytest.mark.skip(reason="Cache warming requires openhcs (not part of core hieraconf)")


def test_prewarm_config_analysis_cache():
    """Test prewarming config analysis cache."""

    @dataclass
    class Config1:
        value: str = "test1"

    @dataclass
    class Config2:
        value: str = "test2"
        nested: Config1 = None

    # Should not raise an error - takes single type, not list
    prewarm_config_analysis_cache(Config2)


def test_prewarm_callable_analysis_cache():
    """Test prewarming callable analysis cache."""

    def sample_function():
        return "test"

    class SampleClass:
        def method(self):
            return "test"

    # Should not raise an error - takes variadic args, not list
    prewarm_callable_analysis_cache(sample_function, SampleClass.method)


def test_prewarm_empty_list():
    """Test prewarming with empty args."""

    # Should handle empty calls gracefully
    @dataclass
    class DummyConfig:
        value: str = "test"

    # Config analysis requires a type
    prewarm_config_analysis_cache(DummyConfig)
    # Callable analysis can be called with no args
    prewarm_callable_analysis_cache()


def test_prewarm_with_none():
    """Test that cache warming handles edge cases."""

    @dataclass
    class MyConfig:
        value: str = None

    # Should not raise error even with None default
    prewarm_config_analysis_cache(MyConfig)
