"""Integration tests for lazy-config."""
import pytest
from dataclasses import dataclass

from lazy_config import (
    set_base_config_type,
    LazyDataclassFactory,
    config_context,
)


def test_readme_quick_start_example():
    """Test the quick start example from README."""
    @dataclass
    class GlobalConfig:
        output_dir: str = "/tmp"
        num_workers: int = 4
        debug: bool = False

    # Initialize framework
    set_base_config_type(GlobalConfig)

    # Create lazy version
    factory = LazyDataclassFactory()
    LazyGlobalConfig = factory.make_lazy_simple(GlobalConfig)

    # Use with context
    global_cfg = GlobalConfig(output_dir="/data", num_workers=8)

    with config_context(global_cfg):
        lazy_cfg = LazyGlobalConfig()
        assert lazy_cfg.output_dir == "/data"
        assert lazy_cfg.debug is False


def test_dual_axis_inheritance():
    """Test dual-axis inheritance (X-axis and Y-axis)."""
    @dataclass
    class BaseConfig:
        base_field: str = "base"
        shared_field: str = "base_shared"

    @dataclass
    class SpecializedConfig(BaseConfig):
        specialized_field: str = "specialized"

    @dataclass
    class GlobalConfig:
        global_field: str = "global"
        shared_field: str = "global_shared"

    LazySpecialized = LazyDataclassFactory.make_lazy_simple(SpecializedConfig)

    global_cfg = GlobalConfig(
        global_field="g1",
        shared_field="from_global"
    )

    specialized_cfg = SpecializedConfig(
        base_field="b1",
        specialized_field="s1",
        shared_field="from_specialized"
    )

    # Test context hierarchy
    with config_context(global_cfg):
        with config_context(specialized_cfg):
            lazy = LazySpecialized()

            # Should resolve from specialized config
            assert lazy.specialized_field == "s1"
            assert lazy.base_field == "b1"
            assert lazy.shared_field == "from_specialized"


def test_nested_contexts():
    """Test nested configuration contexts."""
    @dataclass
    class GlobalConfig:
        level: str = "global"
        value: int = 1

    @dataclass
    class PipelineConfig:
        level: str = "pipeline"
        value: int = 2

    @dataclass
    class StepConfig:
        level: str = "step"
        value: int = 3

    LazyStep = LazyDataclassFactory.make_lazy_simple(StepConfig)

    global_cfg = GlobalConfig(level="g", value=10)
    pipeline_cfg = PipelineConfig(level="p", value=20)
    step_cfg = StepConfig(level="s", value=30)

    # Nested contexts
    with config_context(global_cfg):
        with config_context(pipeline_cfg):
            with config_context(step_cfg):
                lazy = LazyStep()
                # Should resolve from innermost (step) context
                assert lazy.level == "s"
                assert lazy.value == 30


def test_explicit_values_override_context():
    """Test that explicit values override context resolution."""
    @dataclass
    class MyConfig:
        field1: str = "default1"
        field2: str = "default2"

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    context_cfg = MyConfig(field1="context1", field2="context2")

    with config_context(context_cfg):
        # Create lazy with one explicit value
        lazy = LazyConfig(field1="explicit")

        # Explicit value should override context
        assert lazy.field1 == "explicit"
        # Non-explicit value should come from context
        assert lazy.field2 == "context2"


def test_no_context_fallback():
    """Test behavior when no context is available."""
    @dataclass
    class MyConfig:
        value: str = "default"
        number: int = 42

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    # Create lazy instance without context
    lazy = LazyConfig()

    # Should either return None or fall back to defaults
    # Exact behavior depends on implementation
    result = lazy.value
    assert result is None or result == "default"


def test_multiple_configs_in_context():
    """Test using multiple different config types in context."""
    @dataclass
    class DatabaseConfig:
        host: str = "localhost"
        port: int = 5432

    @dataclass
    class CacheConfig:
        ttl: int = 300
        max_size: int = 1000

    LazyDB = LazyDataclassFactory.make_lazy_simple(DatabaseConfig)
    LazyCache = LazyDataclassFactory.make_lazy_simple(CacheConfig)

    db_cfg = DatabaseConfig(host="prod.db.com", port=5433)
    cache_cfg = CacheConfig(ttl=600, max_size=2000)

    # Both configs in context
    with config_context(db_cfg):
        with config_context(cache_cfg):
            lazy_db = LazyDB()
            lazy_cache = LazyCache()

            # Each should resolve from its own config type
            assert lazy_db.host == "prod.db.com"
            assert lazy_db.port == 5433
            assert lazy_cache.ttl == 600
            assert lazy_cache.max_size == 2000


def test_partial_override():
    """Test partial field override in lazy config."""
    @dataclass
    class MyConfig:
        field1: str = "default1"
        field2: str = "default2"
        field3: str = "default3"

    LazyConfig = LazyDataclassFactory.make_lazy_simple(MyConfig)

    context_cfg = MyConfig(
        field1="context1",
        field2="context2",
        field3="context3"
    )

    with config_context(context_cfg):
        # Override only field2
        lazy = LazyConfig(field2="override")

        # Field1 and field3 from context, field2 overridden
        assert lazy.field1 == "context1"
        assert lazy.field2 == "override"
        assert lazy.field3 == "context3"
