"""
Generic global configuration context management.

Provides thread-local storage for global configuration state.
This is used as the base context for all lazy configuration resolution.

DUAL THREAD-LOCAL PATTERN:
- _saved_global_config_contexts: SAVED config (what descendants/compiler see)
- _live_global_config_contexts: LIVE config (what UI sees during editing)

Default behavior: UI uses LIVE (sees unsaved edits)
Explicit override: Compilation uses SAVED (via use_live_global=False)
"""

import threading
from dataclasses import dataclass
from typing import Dict, Type, Optional, Any

# Dual thread-local storage: saved (for descendants/compiler) and live (for UI editing)
_saved_global_config_contexts: Dict[Type, threading.local] = {}
_live_global_config_contexts: Dict[Type, threading.local] = {}


def _validate_global_config_value(config_type: Type, config_instance: Any) -> None:
    """Validate one nominal global-config storage assignment."""

    if not isinstance(config_type, type):
        raise TypeError(f"Global config key must be a type, got {config_type!r}.")
    if not isinstance(config_instance, config_type):
        raise TypeError(
            f"Global config value for {config_type.__name__} must be an "
            f"instance of that type, got {type(config_instance).__name__}."
        )


def _assign_global_config_value(
    contexts: Dict[Type, threading.local], config_type: Type, value: Any
) -> None:
    """One storage boundary for installing or unsetting a context projection."""

    if value is None:
        local = contexts.get(config_type)
        if local is not None and hasattr(local, "value"):
            del local.value
        return
    _validate_global_config_value(config_type, value)
    if config_type not in contexts:
        contexts[config_type] = threading.local()
    contexts[config_type].value = value


@dataclass(frozen=True)
class GlobalContextValues:
    """Prepared saved/live projections, or exact local rollback context values."""

    config_type: Type
    saved: Any
    live: Any

    @classmethod
    def capture(cls, config_type: Type) -> "GlobalContextValues":
        return cls(
            config_type,
            get_saved_global_config(config_type),
            get_live_global_config(config_type),
        )

    def validate(self) -> None:
        for value in (self.saved, self.live):
            if value is not None:
                _validate_global_config_value(self.config_type, value)

    def apply(self) -> None:
        _assign_global_config_value(
            _saved_global_config_contexts, self.config_type, self.saved
        )
        _assign_global_config_value(
            _live_global_config_contexts, self.config_type, self.live
        )


def set_saved_global_config(config_type: Type, config_instance: Any) -> None:
    """Set SAVED global config (what descendants/compiler see).

    Called when:
    - App startup loads cached config
    - User SAVES GlobalPipelineConfig in ConfigWindow
    - Tests set up saved state

    Args:
        config_type: The config type to set
        config_instance: The SAVED config instance
    """
    _validate_global_config_value(config_type, config_instance)
    _assign_global_config_value(
        _saved_global_config_contexts, config_type, config_instance
    )


def set_live_global_config(config_type: Type, config_instance: Any) -> None:
    """Set LIVE global config (what UI sees during editing).

    Called when:
    - User types in GlobalPipelineConfig field (every keystroke)
    - UI needs to show live preview of unsaved changes

    Args:
        config_type: The config type to set
        config_instance: The LIVE (unsaved) config instance
    """
    _validate_global_config_value(config_type, config_instance)
    _assign_global_config_value(
        _live_global_config_contexts, config_type, config_instance
    )


def get_saved_global_config(config_type: Type) -> Optional[Any]:
    """Get SAVED global config (what descendants/compiler see).

    Args:
        config_type: The config type to retrieve

    Returns:
        Saved config instance or None
    """
    context = _saved_global_config_contexts.get(config_type)
    return getattr(context, "value", None) if context else None


def get_live_global_config(config_type: Type) -> Optional[Any]:
    """Get LIVE global config (what UI sees during editing).

    Args:
        config_type: The config type to retrieve

    Returns:
        Live config instance or None
    """
    context = _live_global_config_contexts.get(config_type)
    return getattr(context, "value", None) if context else None


def set_global_config_for_editing(config_type: Type, config_instance: Any) -> None:
    """Set global config for editing (sets BOTH saved and live).

    Use this for app startup and initial setup.
    For live editing updates, use set_live_global_config().
    For saving, use set_saved_global_config().

    Args:
        config_type: The config type to set
        config_instance: The config instance to set
    """
    set_saved_global_config(config_type, config_instance)
    set_live_global_config(config_type, config_instance)


def get_current_global_config(
    config_type: Type, use_live: bool = True
) -> Optional[Any]:
    """Get current global config.

    Args:
        config_type: The config type to retrieve
        use_live: If True (default), return LIVE config (UI sees unsaved edits).
                 If False, return SAVED config (compiler sees saved values).

    Returns:
        Config instance or None
    """
    if use_live:
        return get_live_global_config(config_type)
    else:
        return get_saved_global_config(config_type)
