"""Pytest configuration and shared fixtures."""
import pytest
from dataclasses import dataclass
from objectstate import set_base_config_type
import objectstate.config as config_module
import objectstate.global_config as global_config_module


@dataclass
class TestGlobalConfig:
    """Test global configuration - serves as base config type for tests."""
    output_dir: str = "/tmp"
    num_workers: int = 4
    debug: bool = False
    timeout: int = 30
    # Fields from pipeline config for context merging
    batch_size: int = 32
    learning_rate: float = 0.001
    epochs: int = 10
    # Fields from step config for context merging
    input_size: int = 128
    output_size: int = 64
    dropout: float = 0.1


@dataclass
class TestPipelineConfig:
    """Test pipeline configuration."""
    batch_size: int = 32
    learning_rate: float = 0.001
    epochs: int = 10


@dataclass
class TestStepConfig:
    """Test step configuration."""
    input_size: int = 128
    output_size: int = 64
    dropout: float = 0.1


@pytest.fixture(autouse=True)
def reset_and_init_base_config():
    """Reset and initialize base config type before each test."""
    # Store original values
    original_base_type = config_module._base_config_type
    original_saved = dict(global_config_module._saved_global_config_contexts)
    original_live = dict(global_config_module._live_global_config_contexts)

    # Set up base config type for all tests
    set_base_config_type(TestGlobalConfig)

    yield

    # Restore original values after test
    config_module._base_config_type = original_base_type
    global_config_module._saved_global_config_contexts.clear()
    global_config_module._saved_global_config_contexts.update(original_saved)
    global_config_module._live_global_config_contexts.clear()
    global_config_module._live_global_config_contexts.update(original_live)


@pytest.fixture
def global_config():
    """Provide a test global configuration."""
    return TestGlobalConfig(output_dir="/data", num_workers=8, debug=True)


@pytest.fixture
def pipeline_config():
    """Provide a test pipeline configuration."""
    return TestPipelineConfig(batch_size=64, learning_rate=0.01)


@pytest.fixture
def step_config():
    """Provide a test step configuration."""
    return TestStepConfig(input_size=256, output_size=128)
