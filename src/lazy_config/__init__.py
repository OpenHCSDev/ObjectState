"""
lazy-config: Generic lazy dataclass configuration framework.

This package provides a complete system for hierarchical configuration management
with lazy resolution, dual-axis inheritance, and UI integration.
"""

__version__ = "0.1.0"

from .lazy_factory import (
    LazyDataclassFactory,
    auto_create_decorator,
    register_lazy_type_mapping,
    get_base_type_for_lazy,
    ensure_global_config_context,
)
from .dual_axis_resolver import (
    resolve_field_inheritance,
)
from .context_manager import (
    config_context,
    get_current_temp_global,
    set_current_temp_global,
    clear_current_temp_global,
    merge_configs,
    extract_all_configs,
    get_base_global_config,
)
from .placeholder import LazyDefaultPlaceholderService
from .global_config import (
    set_current_global_config,
    get_current_global_config,
    set_global_config_for_editing,
)
from .config import (
    set_base_config_type,
    get_base_config_type,
)
from .cache_warming import (
    prewarm_config_analysis_cache,
    prewarm_callable_analysis_cache,
)

__all__ = [
    # Factory
    "LazyDataclassFactory",
    "auto_create_decorator",
    "register_lazy_type_mapping",
    "get_base_type_for_lazy",
    "ensure_global_config_context",
    # Resolver
    "resolve_field_inheritance",
    # Context
    "config_context",
    "get_current_temp_global",
    "set_current_temp_global",
    "clear_current_temp_global",
    "merge_configs",
    "extract_all_configs",
    "get_base_global_config",
    # Placeholder
    "LazyDefaultPlaceholderService",
    # Global config
    "set_current_global_config",
    "get_current_global_config",
    "set_global_config_for_editing",
    # Configuration
    "set_base_config_type",
    "get_base_config_type",
    # Cache warming
    "prewarm_config_analysis_cache",
    "prewarm_callable_analysis_cache",
]
