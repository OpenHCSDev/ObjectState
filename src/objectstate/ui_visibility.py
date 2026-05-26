"""Typed UI visibility markers for configuration classes."""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import ClassVar, TypeVar


T = TypeVar("T", bound=type)


class UIVisibilityRegistry:
    """Exact-class registry for config types hidden from UI form navigation."""

    _hidden_types: ClassVar[set[type]] = set()

    @classmethod
    def register_hidden(cls, config_type: T) -> T:
        cls._hidden_types.add(config_type)
        return config_type

    @classmethod
    def is_hidden(cls, config_type: type) -> bool:
        return config_type in cls._hidden_types

    @classmethod
    def is_hidden_candidate(cls, candidate: object) -> bool:
        if not inspect.isclass(candidate):
            return False
        return cls.is_hidden(candidate)


class UISpecialFieldRegistry:
    """Exact-owner registry for fields rendered by custom UI editors."""

    _fields_by_owner: ClassVar[dict[type, frozenset[str]]] = {}

    @classmethod
    def register(cls, owner_type: T, field_names: tuple[str, ...]) -> T:
        if not field_names:
            raise ValueError("UI special field registration requires at least one field")
        cls._fields_by_owner[owner_type] = frozenset(field_names)
        return owner_type

    @classmethod
    def has_special_editor(cls, owner_type: type | None, field_name: str) -> bool:
        if owner_type is None:
            return False
        return field_name in cls._fields_by_owner.get(owner_type, frozenset())


@dataclass(frozen=True)
class UIParameterVisibilityRequest:
    """Visibility request for one parameter field."""

    owner_type: type | None
    field_name: str
    field_type_candidate: object
    field_metadata_hidden: bool = False


class UIParameterVisibilityPolicy:
    """Authority for deciding whether a parameter is omitted from generic UI forms."""

    @classmethod
    def should_hide(cls, request: UIParameterVisibilityRequest) -> bool:
        return (
            UISpecialFieldRegistry.has_special_editor(request.owner_type, request.field_name)
            or request.field_metadata_hidden
            or UIVisibilityRegistry.is_hidden_candidate(request.field_type_candidate)
        )


def mark_ui_hidden_config(config_type: T) -> T:
    """Register a config class as hidden from UI form/navigation surfaces."""

    return UIVisibilityRegistry.register_hidden(config_type)


def is_ui_hidden_config_type(config_type: type) -> bool:
    """Return True when a config class is explicitly hidden from UI surfaces."""

    return UIVisibilityRegistry.is_hidden(config_type)


def is_ui_hidden_config_candidate(candidate: object) -> bool:
    """Return True when an object is an explicitly hidden config class."""

    return UIVisibilityRegistry.is_hidden_candidate(candidate)


def mark_ui_special_fields(*field_names: str):
    """Decorator registering fields handled by custom UI editors."""

    def decorator(owner_type: T) -> T:
        return UISpecialFieldRegistry.register(owner_type, field_names)

    return decorator


def has_ui_special_field(owner_type: type | None, field_name: str) -> bool:
    """Return True when a field is owned by a custom UI editor."""

    return UISpecialFieldRegistry.has_special_editor(owner_type, field_name)


def should_hide_ui_parameter(request: UIParameterVisibilityRequest) -> bool:
    """Return True when a parameter should be omitted from generic UI forms."""

    return UIParameterVisibilityPolicy.should_hide(request)
