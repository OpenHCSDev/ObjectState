"""Pytest configuration and shared fixtures."""
import pytest
from dataclasses import dataclass
from lazy_config import set_base_config_type


@dataclass
class TestGlobalConfig:
    """Test global configuration."""
    output_dir: str = "/tmp"
    num_workers: int = 4
    debug: bool = False
    timeout: int = 30


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
def reset_base_config():
    """Reset base config type before each test."""
    # Import the module to access the global variable
    import lazy_config.config as config_module

    # Store original value
    original = config_module._base_config_type

    # Set to None before test
    config_module._base_config_type = None

    yield

    # Restore original value after test
    config_module._base_config_type = original


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
