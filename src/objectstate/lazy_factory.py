"""Generic lazy dataclass factory using flexible resolution."""

# Standard library imports
import dataclasses
import logging
import re
import sys
from abc import ABC
from contextlib import contextmanager
from functools import lru_cache

from dataclasses import dataclass, fields, is_dataclass, make_dataclass, MISSING, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar, Union, get_type_hints

from objectstate.ui_visibility import mark_ui_hidden_config
from python_introspect import (
    make_optional,
    register_type_resolver,
    resolve_annotated,
    resolve_optional,
)

# Note: dual_axis_resolver_recursive and lazy_placeholder imports kept inline to avoid circular imports


# Type registry for lazy dataclass to base class mapping
_lazy_type_registry: Dict[Type, Type] = {}

# Reverse registry for base class to lazy dataclass mapping (for O(1) lookup)
_base_to_lazy_registry: Dict[Type, Type] = {}


def _resolved_dataclass_annotations(dataclass_type: type) -> Dict[str, object]:
    """Resolve declarations even while a class decorator precedes module binding."""

    return get_type_hints(
        dataclass_type,
        localns={dataclass_type.__name__: dataclass_type},
        include_extras=True,
    )


# =============================================================================
# UNIFIED NONE-FORCING: Single path for both base and lazy classes
# Replaces the old 3-stage approach (pre-process setattr, post-process Field patch)
# =============================================================================

def get_inherited_field_names(cls: Type) -> set:
    """
    Get names of fields inherited from parent dataclasses (not defined in cls itself).

    A field is "inherited" if it exists in a parent's __dataclass_fields__ but
    is NOT in this class's own __annotations__ (i.e., not redefined here).
    """
    # Get all field names from parent dataclasses
    parent_fields = set()
    for base in cls.__mro__[1:]:  # Skip cls itself
        if dataclasses.is_dataclass(base):
            parent_fields.update(base.__dataclass_fields__.keys())

    # Get cls's OWN annotations (not inherited) - check __dict__ not getattr
    own_defined = set()
    if '__annotations__' in cls.__dict__:
        own_defined = set(cls.__dict__['__annotations__'].keys())

    return parent_fields - own_defined


def _inherited_default_metadata(field_definition) -> dict:
    """Preserve one concrete dataclass field's standalone fallback values."""

    metadata = dict(field_definition.metadata)
    metadata.setdefault(
        "_inherited_default",
        (
            field_definition.default
            if field_definition.default is not MISSING
            else MISSING
        ),
    )
    metadata.setdefault(
        "_inherited_default_factory",
        field_definition.default_factory,
    )
    return metadata


def rebuild_with_none_defaults(
    cls: Type,
    field_names_to_none: Optional[set] = None,
    new_name: Optional[str] = None
) -> Type:
    """
    Rebuild a dataclass via make_dataclass with None defaults for specified fields.

    This is the UNIFIED approach for both base classes (inherit_as_none) and lazy classes.
    Instead of patching Field objects after @dataclass, we rebuild with correct defaults.

    Args:
        cls: The dataclass to rebuild
        field_names_to_none: Fields that should have default=None.
                            If None, ALL fields get default=None (for lazy classes).
        new_name: Optional new class name (for lazy classes)

    Returns:
        A new class with the same fields but modified defaults
    """
    import copy

    if not dataclasses.is_dataclass(cls):
        raise ValueError(f"{cls} is not a dataclass")

    if field_names_to_none is None:
        # All fields get None (for lazy classes)
        field_names_to_none = {f.name for f in fields(cls)}

    annotations = _resolved_dataclass_annotations(cls)

    # Build field definitions
    field_defs = []
    for f in fields(cls):
        declared_type = annotations.get(f.name, f.type)
        if f.name in field_names_to_none:
            # Force None default, but preserve original default in metadata for fallback
            # This allows standalone usage to fall back to parent's static default
            field_defs.append(
                (
                    f.name,
                    make_optional(declared_type),
                    field(
                        default=None,
                        metadata=_inherited_default_metadata(f),
                    ),
                )
            )
        else:
            # Preserve original field (copy to avoid sharing)
            field_defs.append((f.name, declared_type, copy.copy(f)))

    # Collect non-dunder attributes to preserve (methods, class vars, etc.)
    namespace = {}
    for key, value in cls.__dict__.items():
        if key.startswith('__') and key.endswith('__'):
            # Skip most dunders (make_dataclass will generate them)
            # BUT preserve __registry_key__ for AutoRegisterMeta
            if key != '__registry_key__':
                continue
        if key == '__dataclass_fields__':
            continue  # Will be regenerated
        namespace[key] = value

    # Keep original bases for isinstance() to work
    bases = cls.__bases__

    # Check if any base is a frozen dataclass - if so, new class must also be frozen
    is_frozen = any(
        dataclasses.is_dataclass(b) and b.__dataclass_fields__ and
        getattr(b, '__dataclass_params__', None) and b.__dataclass_params__.frozen
        for b in cls.__mro__[1:]
    )

    # Get the original metaclass to preserve it
    orig_metaclass = type(cls)

    # Create new class
    new_cls = make_dataclass(
        new_name or cls.__name__,
        fields=field_defs,
        bases=bases,
        namespace=namespace,
        frozen=is_frozen,
    )

    # Preserve module and qualname
    new_cls.__module__ = cls.__module__
    if new_name is None:
        new_cls.__qualname__ = cls.__qualname__

    # Preserve original metaclass if it's not just type
    # This is critical for AutoRegisterMeta and other custom metaclasses
    if orig_metaclass is not type:
        # Re-create the class with the original metaclass
        # We need to do this because make_dataclass doesn't accept metaclass parameter
        # But we must NOT re-apply @dataclass since make_dataclass already did that
        new_cls = orig_metaclass(
            new_cls.__name__,
            new_cls.__bases__,
            dict(new_cls.__dict__),
        )

    return new_cls


def replace_raw(instance, **changes):
    """
    Replace dataclass fields while preserving raw None values.

    Unlike dataclasses.replace(), this function uses object.__getattribute__
    to get field values, preventing lazy resolution from being triggered.
    This is critical for lazy dataclasses where None means "inherit from parent"
    and must not be resolved during copy operations.

    Args:
        instance: The dataclass instance to copy
        **changes: Field values to override

    Returns:
        A new instance with raw values preserved (not resolved)
    """
    if not is_dataclass(instance):
        raise TypeError(f"replace_raw() should be called on dataclass instances, got {type(instance)}")

    # Get all field values using object.__getattribute__ to avoid lazy resolution
    field_values = {}
    for f in fields(instance):
        if f.name in changes:
            field_values[f.name] = changes[f.name]
        else:
            # Use object.__getattribute__ to get raw value (bypass lazy __getattribute__)
            field_values[f.name] = object.__getattribute__(instance, f.name)

    # Create new instance with raw values
    return type(instance)(**field_values)


# ContextEventCoordinator removed - replaced with contextvars-based context system




def register_lazy_type_mapping(lazy_type: Type, base_type: Type) -> None:
    """Register mapping between lazy dataclass type and its base type."""
    if not isinstance(lazy_type, type) or not isinstance(base_type, type):
        raise TypeError("Lazy type mappings require two types.")
    existing_base = _lazy_type_registry.get(lazy_type)
    if existing_base is not None and existing_base is not base_type:
        raise ValueError(
            f"{lazy_type.__name__} is already registered for "
            f"{existing_base.__name__}, not {base_type.__name__}."
        )
    existing_lazy = _base_to_lazy_registry.get(base_type)
    if existing_lazy is not None and existing_lazy is not lazy_type:
        raise ValueError(
            f"{base_type.__name__} already owns lazy type "
            f"{existing_lazy.__name__}, not {lazy_type.__name__}."
        )
    _lazy_type_registry[lazy_type] = base_type
    _base_to_lazy_registry[base_type] = lazy_type


def get_base_type_for_lazy(lazy_type: Type) -> Optional[Type]:
    """Get the base type for a lazy dataclass type."""
    return _lazy_type_registry.get(lazy_type)


register_type_resolver(get_base_type_for_lazy)


def is_lazy_dataclass(obj_or_type) -> bool:
    """
    Check if an object or type is a lazy dataclass.

    ANTI-DUCK-TYPING: Uses isinstance() check against LazyDataclass base class
    instead of hasattr() attribute sniffing.

    Works with both instances and types, and naturally handles Optional types
    without unwrapping.

    Args:
        obj_or_type: Either a dataclass instance or a dataclass type

    Returns:
        True if the object/type is a lazy dataclass

    Examples:
        >>> is_lazy_dataclass(PipelineConfig)  # True (type check)
        >>> is_lazy_dataclass(GlobalPipelineConfig)  # False
        >>> is_lazy_dataclass(pipeline_config_instance)  # True (instance check)
        >>> is_lazy_dataclass(LazyPathPlanningConfig)  # True
        >>> is_lazy_dataclass(PathPlanningConfig)  # False

        # Works with Optional without unwrapping!
        >>> config: Optional[PipelineConfig] = PipelineConfig()
        >>> is_lazy_dataclass(config)  # True - checks the instance, not the type annotation
    """
    if isinstance(obj_or_type, type):
        # Type check: is it a subclass of LazyDataclass?
        return issubclass(obj_or_type, LazyDataclass)
    else:
        # Instance check: is it an instance of LazyDataclass?
        return isinstance(obj_or_type, LazyDataclass)

logger = logging.getLogger(__name__)


# =============================================================================
# GENERIC SCOPE RULE: Virtual base class for global configs using __instancecheck__
# This allows isinstance() checks without actual inheritance, so lazy versions don't inherit it
# =============================================================================


_GLOBAL_CONFIG_TYPES: set[type] = set()


def mark_global_config_type(config_type: Type) -> Type:
    """Register config_type as an ObjectState global-config authority."""
    if not isinstance(config_type, type) or not is_dataclass(config_type):
        raise TypeError("Global config authorities must be dataclass types.")
    _GLOBAL_CONFIG_TYPES.add(config_type)
    return config_type


class GlobalConfigMeta(type):
    """
    Metaclass that makes isinstance(obj, GlobalConfigBase) use the global config registry.

    This enables type-safe isinstance checks without inheritance:
        if isinstance(config, GlobalConfigBase):  # Returns True for GlobalPipelineConfig
                                                   # Returns False for PipelineConfig (lazy version)
    """
    def __instancecheck__(cls, instance):
        return is_global_config_type(type(instance))


class GlobalConfigBase(metaclass=GlobalConfigMeta):
    """
    Virtual base class for all global config types.

    Uses custom metaclass to check the global config registry instead of actual inheritance.
    This prevents lazy versions (PipelineConfig) from being considered global configs.

    Usage:
        if isinstance(config, GlobalConfigBase):  # Generic, works for any global config

    Instead of:
        if isinstance(config, GlobalPipelineConfig):  # Hardcoded, breaks extensibility
    """
    pass


class LazyResolutionDataclass(ABC):
    """Nominal root for dataclasses whose ``None`` fields resolve by context."""


class LazyDataclass(LazyResolutionDataclass):
    """
    Base class for all lazy dataclasses created by LazyDataclassFactory.

    This enables isinstance() checks without duck typing or unwrapping:
        isinstance(config, LazyDataclass)  # Works!
        isinstance(optional_config, LazyDataclass)  # Works even for Optional!

    All lazy dataclasses inherit from this, regardless of naming convention:
    - PipelineConfig (lazy version of GlobalPipelineConfig)
    - LazyPathPlanningConfig
    - LazyWellFilterConfig
    - etc.

    ANTI-DUCK-TYPING: Use isinstance(obj, LazyDataclass) instead of hasattr() checks.
    """
    pass


def has_lazy_resolution(obj_or_type: object) -> bool:
    """Return whether a value or declared type owns lazy field resolution."""

    candidate = resolve_optional(obj_or_type)
    if isinstance(candidate, type):
        return issubclass(candidate, LazyResolutionDataclass)
    return isinstance(candidate, LazyResolutionDataclass)


def is_global_config_type(config_type: Type) -> bool:
    """
    Check if a config type is a global config (marked by @auto_create_decorator).

    GENERIC SCOPE RULE: Use this instead of hardcoding class name checks like:
        if config_class == GlobalPipelineConfig:

    Instead use:
        if is_global_config_type(config_class):

    Args:
        config_type: The config class to check

    Returns:
        True if the type is marked as a global config, False otherwise
    """
    return config_type in _GLOBAL_CONFIG_TYPES


def is_global_config_instance(config_instance: Any) -> bool:
    """
    Check if a config instance is an instance of a global config class.

    GENERIC SCOPE RULE: Use this instead of hardcoding isinstance checks like:
        if isinstance(config, GlobalPipelineConfig):

    Instead use:
        if is_global_config_instance(config):

    Or use the virtual base class:
        if isinstance(config, GlobalConfigBase):

    Args:
        config_instance: The config instance to check

    Returns:
        True if the instance is of a global config type, False otherwise
    """
    return is_global_config_type(type(config_instance))


def get_lazy_type_for_base(base_type: Type) -> Optional[Type]:
    """Get the lazy type for a base dataclass type."""
    return _base_to_lazy_registry.get(base_type)


def _normalized_config_type(annotation: object) -> Optional[type]:
    """Return the nominal config owner declared by one field annotation."""

    candidate = resolve_optional(resolve_annotated(annotation))
    if not isinstance(candidate, type):
        return None
    return get_base_type_for_lazy(candidate) or candidate


@lru_cache(maxsize=None)
def _declared_config_field_names(
    owner_type: type,
    config_type: type,
) -> Tuple[str, ...]:
    """Find fields whose resolved declaration owns ``config_type``."""

    if not is_dataclass(owner_type):
        raise TypeError(f"{owner_type!r} is not a dataclass type.")
    config_base = get_base_type_for_lazy(config_type) or config_type
    annotations = _resolved_dataclass_annotations(owner_type)
    return tuple(
        field_definition.name
        for field_definition in fields(owner_type)
        if _normalized_config_type(
            annotations.get(field_definition.name, field_definition.type)
        )
        is config_base
    )


def _single_declared_config_field(
    owner_type: type,
    config_type: type,
    *,
    required: bool,
) -> Optional[str]:
    """Select one annotation-owned config field and reject ambiguity."""

    field_names = _declared_config_field_names(owner_type, config_type)
    if len(field_names) == 1:
        return field_names[0]
    if not field_names and not required:
        return None
    config_base = get_base_type_for_lazy(config_type) or config_type
    if not field_names:
        raise TypeError(
            f"{owner_type.__name__} has no field declared as "
            f"{config_base.__name__}."
        )
    raise TypeError(
        f"{owner_type.__name__} declares multiple {config_base.__name__} "
        f"fields: {', '.join(field_names)}."
    )


# =============================================================================
# Constants for lazy configuration system - simplified from class to module-level
MATERIALIZATION_DEFAULTS_PATH = "materialization_defaults"
RESOLVE_FIELD_VALUE_METHOD = "_resolve_field_value"
GET_ATTRIBUTE_METHOD = "__getattribute__"
TO_BASE_CONFIG_METHOD = "to_base_config"
FROM_CONFIG_METHOD = "from_config"
WITH_DEFAULTS_METHOD = "with_defaults"
WITH_OVERRIDES_METHOD = "with_overrides"
LAZY_FIELD_DEBUG_TEMPLATE = "LAZY FIELD CREATION: {field_name} - original={original_type}, has_default={has_default}, final={final_type}"

LAZY_CLASS_NAME_PREFIX = "Lazy"

# Legacy helper functions removed - new context system handles all resolution


# Functional fallback strategies
def _get_raw_field_value(obj: Any, field_name: str) -> Any:
    """
    Get raw field value bypassing lazy property getters to prevent infinite recursion.

    Uses object.__getattribute__() to access stored values directly without triggering
    lazy resolution, which would create circular dependencies in the resolution chain.

    Args:
        obj: Object to get field from
        field_name: Name of field to access

    Returns:
        Raw field value or None if field doesn't exist

    Raises:
        AttributeError: If field doesn't exist (fail-loud behavior)
    """
    try:
        return object.__getattribute__(obj, field_name)
    except AttributeError:
        return None


def bind_lazy_resolution_to_class(cls: Type) -> None:
    """
    Add lazy __getattribute__ to an existing class.

    This enables concrete classes (like WellFilterConfig stored in
    GlobalPipelineConfig) to resolve None values via MRO without
    changing their static defaults.

    Args:
        cls: The class to add lazy resolution to
    """
    if has_lazy_resolution(cls):
        return

    lazy_getattribute = LazyMethodBindings.create_getattribute()
    cls.__getattribute__ = lazy_getattribute
    LazyResolutionDataclass.register(cls)


@dataclass(frozen=True)
class LazyMethodBindings:
    """Declarative method bindings for lazy dataclasses."""

    @staticmethod
    def create_resolver() -> Callable[[Any, str], Any]:
        """Create field resolver method using new pure function interface."""
        from objectstate.dual_axis_resolver import resolve_field_inheritance
        from objectstate.context_manager import current_temp_global, extract_all_configs

        def _resolve_field_value(self, field_name: str) -> Any:
            # Get current context from contextvars
            try:
                current_context = current_temp_global.get()
                # Extract available configs from current context
                available_configs = extract_all_configs(current_context)

                # Use pure function for resolution
                return resolve_field_inheritance(self, field_name, available_configs)
            except LookupError:
                # No context available - return None (fail-loud approach)
                logger.debug(f"No context available for resolving {type(self).__name__}.{field_name}")
                return None

        return _resolve_field_value

    @staticmethod
    def create_getattribute() -> Callable[[Any, str], Any]:
        """Create lazy __getattribute__ method using new context system."""
        from objectstate.dual_axis_resolver import resolve_field_inheritance, _has_concrete_field_override
        from objectstate.context_manager import current_temp_global, extract_all_configs

        def _find_mro_concrete_value(base_class, name):
            """Extract common MRO traversal pattern."""
            return next((getattr(cls, name) for cls in base_class.__mro__
                        if _has_concrete_field_override(cls, name)), None)

        def __getattribute__(self: Any, name: str) -> Any:
            """
            Three-stage resolution using new context system.

            Stage 1: Check instance value
            Stage 2: Simple field path lookup in current scope's merged config
            Stage 3: Inheritance resolution using same merged context
            """
            # Stage 1: Get instance value
            value = object.__getattribute__(self, name)
            # Fast path: non-None values never need resolution
            if value is not None:
                return value
            # PERFORMANCE: Use pre-computed frozenset (O(1) lookup) instead of
            # rebuilding {f.name for f in fields(self.__class__)} (O(n)) on every access.
            # Use object.__getattribute__ for __class__ to avoid recursion.
            # Lazily populate if not yet set (e.g. class created outside _create_lazy_dataclass_unified).
            _cls = object.__getattribute__(self, '__class__')
            try:
                _fns = _cls._field_names_set
            except AttributeError:
                _ft = fields(_cls)
                _fns = frozenset(f.name for f in _ft)
                _cls._field_names_set = _fns
                _cls._fields_by_name = {f.name: f for f in _ft}
            if name not in _fns:
                return value

            # Stage 2: Simple field path lookup in current scope's merged global
            try:
                current_context = current_temp_global.get()
                if current_context is not None:
                    config_field_name = _single_declared_config_field(
                        type(current_context),
                        type(self),
                        required=False,
                    )
                    if config_field_name is not None:
                        config_instance = getattr(
                            current_context,
                            config_field_name,
                        )
                        if config_instance is not None:
                            resolved_value = object.__getattribute__(
                                config_instance,
                                name,
                            )
                            if resolved_value is not None:
                                return resolved_value
            except LookupError:
                # No context available, continue to inheritance
                pass

            # Stage 3: Inheritance resolution using same merged context
            try:
                current_context = current_temp_global.get()
                available_configs = extract_all_configs(current_context)
                resolved_value = resolve_field_inheritance(self, name, available_configs)

                if resolved_value is not None:
                    return resolved_value

                # For nested dataclass fields, return lazy instance
                # PERFORMANCE: O(1) dict lookup instead of O(n) linear scan
                _fbm = getattr(self.__class__, '_fields_by_name', None)
                if _fbm is None:
                    _ft = fields(self.__class__)
                    _fbm = {f.name: f for f in _ft}
                    self.__class__._fields_by_name = _fbm
                field_obj = _fbm.get(name)
                if field_obj and is_dataclass(field_obj.type):
                    return field_obj.type()

                # Fallback to inherited default from parent class (for standalone usage)
                if field_obj and '_inherited_default' in field_obj.metadata:
                    inherited = field_obj.metadata['_inherited_default']
                    if inherited is not MISSING:
                        return inherited
                    # Check for default_factory
                    factory = field_obj.metadata.get('_inherited_default_factory', MISSING)
                    if factory is not MISSING:
                        return factory()

                return None

            except LookupError:
                # No context available - fallback to MRO concrete values
                # For LazyDataclass types, get the base type; for concrete types, use self.__class__ directly
                base_type = get_base_type_for_lazy(self.__class__) or self.__class__
                mro_value = _find_mro_concrete_value(base_type, name)
                if mro_value is not None:
                    return mro_value

                # Also check inherited default metadata
                # PERFORMANCE: O(1) dict lookup instead of O(n) linear scan
                _fbm = getattr(self.__class__, '_fields_by_name', None)
                if _fbm is None:
                    _ft = fields(self.__class__)
                    _fbm = {f.name: f for f in _ft}
                    self.__class__._fields_by_name = _fbm
                field_obj = _fbm.get(name)
                if field_obj and '_inherited_default' in field_obj.metadata:
                    inherited = field_obj.metadata['_inherited_default']
                    if inherited is not MISSING:
                        return inherited
                    factory = field_obj.metadata.get('_inherited_default_factory', MISSING)
                    if factory is not MISSING:
                        return factory()

                return None
        return __getattribute__

    @staticmethod
    def create_to_base_config(base_class: Type) -> Callable[[Any], Any]:
        """Create base config converter method."""
        def to_base_config(self):
            # CRITICAL FIX: Use object.__getattribute__ to preserve raw None values
            # getattr() triggers lazy resolution, converting None to static defaults
            # None values must be preserved for dual-axis inheritance to work correctly
            #
            # Context: to_base_config() is called DURING config_context() setup (line 124 in context_manager.py)
            # If we use getattr() here, it triggers resolution BEFORE the context is fully set up,
            # causing resolution to use the wrong/stale context and losing the GlobalPipelineConfig base.
            # We must extract raw None values here, let config_context() merge them into the hierarchy,
            # and THEN resolution happens later with the properly built context.
            field_values = {f.name: object.__getattribute__(self, f.name) for f in fields(self)}
            return base_class(**field_values)
        return to_base_config

    @staticmethod
    def create_from_config(base_class: Type) -> classmethod:
        """Create one generic concrete projection and composition constructor."""

        def from_config(cls, *configs, inherited=None):
            if len(configs) == 1 and isinstance(configs[0], base_class):
                config = configs[0]
                if isinstance(config, LazyDataclass):
                    raise TypeError(
                        f"{cls.__name__}.from_config requires concrete "
                        f"{base_class.__name__}, got {type(config).__name__}."
                    )
                if inherited is not None and (
                    isinstance(inherited, LazyDataclass)
                    or not isinstance(inherited, base_class)
                ):
                    raise TypeError(
                        f"{cls.__name__}.from_config inherited value must be "
                        f"{base_class.__name__}, got {type(inherited).__name__}."
                    )

                values = {}
                for field_definition in fields(base_class):
                    if not field_definition.init:
                        continue
                    value = object.__getattribute__(config, field_definition.name)
                    if inherited is not None and value == object.__getattribute__(
                        inherited,
                        field_definition.name,
                    ):
                        continue
                    values[field_definition.name] = value
                return cls(**values)

            if inherited is not None:
                raise TypeError(
                    f"{cls.__name__}.from_config accepts inherited only when "
                    f"projecting one {base_class.__name__}."
                )
            values = {}
            for config in configs:
                if isinstance(config, LazyDataclass):
                    raise TypeError(
                        f"{cls.__name__}.from_config requires concrete dataclass "
                        f"values, got {type(config).__name__}."
                    )
                lazy_type = get_lazy_type_for_base(type(config))
                if lazy_type is None:
                    raise TypeError(
                        f"{cls.__name__}.from_config has no registered lazy type "
                        f"for {type(config).__name__}."
                    )
                field_name = _single_declared_config_field(
                    cls,
                    type(config),
                    required=True,
                )
                if field_name in values:
                    raise ValueError(
                        f"{cls.__name__}.from_config received duplicate config "
                        f"values for {field_name!r}."
                    )
                values[field_name] = lazy_type.from_config(config)
            return cls(**values)

        return classmethod(from_config)

    @staticmethod
    def create_class_methods() -> Dict[str, Any]:
        """Create class-level utility methods."""
        return {
            WITH_DEFAULTS_METHOD: classmethod(lambda cls: cls()),
            WITH_OVERRIDES_METHOD: classmethod(lambda cls, **kwargs: cls(**kwargs))
        }


class LazyDataclassFactory:
    """Generic factory for creating lazy dataclasses with flexible resolution."""





    @staticmethod
    def _introspect_dataclass_fields(
        base_class: Type,
        debug_template: str,
    ) -> List[Tuple[str, Type, None]]:
        """
        Introspect dataclass fields for lazy loading.

        Converts nested dataclass fields to lazy equivalents and makes fields Optional
        if they lack defaults. Complex logic handles type unwrapping and lazy nesting.
        """
        base_fields = fields(base_class)
        annotations = _resolved_dataclass_annotations(base_class)
        lazy_field_definitions = []

        for field_definition in base_fields:
            # Check if field has default value or factory
            has_default = (
                field_definition.default is not MISSING
                or field_definition.default_factory is not MISSING
            )

            # Check if field type is a dataclass that should be made lazy
            field_type = annotations.get(
                field_definition.name,
                field_definition.type,
            )
            lazy_nested_type = None  # Track if we created a lazy nested type
            nested_type = resolve_annotated(field_type)
            nested_is_registered_lazy = (
                isinstance(nested_type, type)
                and (
                    get_base_type_for_lazy(nested_type) is not None
                    or get_lazy_type_for_base(nested_type) is not None
                    or has_lazy_resolution(nested_type)
                )
            )
            if is_dataclass(nested_type) and nested_is_registered_lazy:
                if get_base_type_for_lazy(nested_type) is not None:
                    lazy_nested_type = nested_type
                else:
                    lazy_nested_type = get_lazy_type_for_base(nested_type)
                if lazy_nested_type is None:
                    lazy_nested_type = LazyDataclassFactory.make_lazy_simple(
                        base_class=nested_type,
                        lazy_class_name=f"Lazy{nested_type.__name__}"
                    )
                field_type = lazy_nested_type
                logger.debug(f"Created lazy class for {field_definition.name}: {nested_type} -> {lazy_nested_type}")

            # CRITICAL FIX: For lazy configs, nested dataclass fields should use default_factory
            # to provide lazy instances (e.g., LazyPathPlanningConfig), not None.
            # This allows getattr(pipeline_config, 'path_planning_config') to return an instance.
            # Non-dataclass fields still default to None for placeholder inheritance.
            # CRITICAL: Always preserve metadata from original field (e.g., ui_hidden flag)
            if lazy_nested_type is not None:
                final_field_type = field_type
                # Nested dataclass field: use default_factory so accessing returns an instance
                # This matches AbstractStep pattern: napari_streaming_config = LazyNapariStreamingConfig()
                field_def = (
                    field_definition.name,
                    final_field_type,
                    dataclasses.field(
                        default_factory=lazy_nested_type,
                        metadata=field_definition.metadata,
                    ),
                )
            else:
                final_field_type = make_optional(field_type)
                # CRITICAL FIX: For lazy configs, ALL non-dataclass fields should default to None
                # This enables proper inheritance from parent configs and placeholder styling
                field_def = (
                    field_definition.name,
                    final_field_type,
                    dataclasses.field(
                        default=None,
                        metadata=_inherited_default_metadata(field_definition),
                    ),
                )

            lazy_field_definitions.append(field_def)

            # Debug logging with provided template (reduced to DEBUG level to reduce log pollution)
            logger.debug(debug_template.format(
                field_name=field_definition.name,
                original_type=field_definition.type,
                has_default=has_default,
                final_type=final_field_type
            ))

        return lazy_field_definitions

    @staticmethod
    def _create_lazy_dataclass_unified(
        base_class: Type,
        lazy_class_name: str,
        debug_template: str,
    ) -> Type:
        """
        Create lazy dataclass with declarative configuration.

        Core factory method that creates lazy dataclass with introspected fields,
        binds resolution methods, and registers type mappings. Complex orchestration
        of field analysis, method binding, and class creation.
        """
        if not is_dataclass(base_class):
            raise ValueError(f"{base_class} must be a dataclass")

        registered_type = get_lazy_type_for_base(base_class)
        if registered_type is not None:
            if registered_type.__name__ != lazy_class_name:
                raise ValueError(
                    f"{base_class.__name__} already owns lazy type "
                    f"{registered_type.__name__}; cannot also create "
                    f"{lazy_class_name}."
                )
            return registered_type

        # Create lazy dataclass with introspected fields
        # CRITICAL FIX: Avoid inheriting from classes with custom metaclasses to prevent descriptor conflicts
        # Exception: InheritAsNoneMeta is safe to inherit from as it only modifies field defaults
        # Classes processed by the global-config decorator own lazy resolution
        # nominally and are safe even when they use a custom metaclass.
        base_metaclass = type(base_class)
        has_unsafe_metaclass = (
            (hasattr(base_class, '__metaclass__') or base_metaclass != type) and
            not has_lazy_resolution(base_class)
        )

        # Determine inheritance: always include LazyDataclass, optionally include base_class
        if has_unsafe_metaclass:
            # Base class has unsafe custom metaclass - don't inherit, just copy interface
            logger.debug(
                "Lazy factory: %s has custom metaclass %s, avoiding inheritance",
                base_class.__name__,
                base_metaclass.__name__,
            )
            bases = (LazyDataclass,)  # Only inherit from LazyDataclass
        else:
            # Safe to inherit from regular dataclass
            bases = (base_class, LazyDataclass)  # Inherit from both

        # Check if base_class is frozen - must match to avoid inheritance error
        # "cannot inherit frozen dataclass from a non-frozen one" and vice versa
        base_is_frozen = (
            is_dataclass(base_class) and
            hasattr(base_class, '__dataclass_params__') and
            base_class.__dataclass_params__.frozen
        )

        # Single make_dataclass call - no duplication
        lazy_class = make_dataclass(
            lazy_class_name,
            LazyDataclassFactory._introspect_dataclass_fields(
                base_class,
                debug_template,
            ),
            bases=bases,
            frozen=base_is_frozen  # Match base class frozen status
        )

        # PERFORMANCE: Cache field names set and field-by-name dict per class.
        # These are derived from dataclasses.fields() which is immutable after class creation.
        # Avoids O(n) set creation on every __getattribute__ call and O(n) linear scan
        # on every field lookup.
        from dataclasses import fields as _dc_fields
        _field_tuple = _dc_fields(lazy_class)
        lazy_class._field_names_set = frozenset(f.name for f in _field_tuple)
        lazy_class._fields_by_name = {f.name: f for f in _field_tuple}

        # Add constructor parameter tracking to detect user-set fields
        original_init = lazy_class.__init__
        def __init_with_tracking__(self, **kwargs):
            # Track which fields were explicitly passed to constructor
            object.__setattr__(self, '_explicitly_set_fields', set(kwargs.keys()))
            original_init(self, **kwargs)

        lazy_class.__init__ = __init_with_tracking__

        # Bind methods declaratively - inline single-use method
        method_bindings = {
            RESOLVE_FIELD_VALUE_METHOD: LazyMethodBindings.create_resolver(),
            GET_ATTRIBUTE_METHOD: LazyMethodBindings.create_getattribute(),
            TO_BASE_CONFIG_METHOD: LazyMethodBindings.create_to_base_config(base_class),
            FROM_CONFIG_METHOD: LazyMethodBindings.create_from_config(base_class),
            **LazyMethodBindings.create_class_methods()
        }
        for method_name, method_impl in method_bindings.items():
            setattr(lazy_class, method_name, method_impl)

        # CRITICAL: Preserve original module for proper imports in generated code
        # make_dataclass() sets __module__ to the caller's module (lazy_factory.py)
        # We need to set it to the base class's original module for correct import paths
        lazy_class.__module__ = base_class.__module__

        # Automatically register the lazy dataclass with the type registry
        register_lazy_type_mapping(lazy_class, base_class)

        return lazy_class





    @staticmethod
    def make_lazy_simple(
        base_class: Type,
        lazy_class_name: str = None
    ) -> Type:
        """
        Create lazy dataclass using new contextvars system.

        SIMPLIFIED: No complex hierarchy providers or field path detection needed.
        Uses new contextvars system for all resolution.

        Args:
            base_class: Base dataclass to make lazy
            lazy_class_name: Optional name for the lazy class

        Returns:
            Generated lazy dataclass with contextvars-based resolution
        """
        # Generate class name if not provided
        lazy_class_name = lazy_class_name or f"Lazy{base_class.__name__}"

        return LazyDataclassFactory._create_lazy_dataclass_unified(
            base_class=base_class,
            lazy_class_name=lazy_class_name,
            debug_template=f"Simple contextvars resolution for {base_class.__name__}",
        )

    # All legacy methods removed - use make_lazy_simple() for all use cases


# =============================================================================
# Constructor Patching for Code Execution
# =============================================================================

@contextmanager
def patch_lazy_constructors(types: Optional[List[Type]] = None):
    """
    Context manager that patches lazy dataclass constructors to preserve None vs concrete distinction.

    This is critical for code editors that use exec() to create dataclass instances.
    Without patching, lazy dataclasses would resolve None values to concrete defaults
    during construction, making it impossible to distinguish between explicitly set
    values and inherited values.

    The patched constructor sets fields provided in kwargs and otherwise uses the
    dataclass defaults/default_factory (or None if none exist). This preserves the
    None vs concrete distinction while still instantiating nested lazy configs.

    Args:
        types: Optional list of lazy types to patch. If None, uses every type
            in the authoritative lazy-to-base registry.

    Usage:
        # Patch during code execution
        with patch_lazy_constructors():
            exec(code_string, namespace)
            # Lazy dataclasses created during exec() will preserve None values

    Example:
        # Without patching:
        LazyZarrConfig(compression='gzip')  # All unspecified fields resolve to defaults

        # With patching:
        with patch_lazy_constructors():
            LazyZarrConfig(compression='gzip')  # Only compression is set, rest are None
    """
    lazy_types = (
        list(_lazy_type_registry)
        if types is None
        else list(types)
    )

    if not lazy_types:
        # No types to patch - just yield
        yield
        return

    # Store original constructors
    original_constructors: Dict[Type, callable] = {}

    # Patch all lazy types
    for lazy_type in lazy_types:
        # Store original constructor
        original_constructors[lazy_type] = lazy_type.__init__

        # Create patched constructor that uses raw values
        def create_patched_init(dataclass_type):
            def patched_init(self, **kwargs):
                # Use raw value approach instead of calling original constructor
                # This prevents lazy resolution during code execution, while still
                # honoring default_factory for nested lazy configs so attributes
                # are not left as None (e.g., path_planning_config).
                for field_definition in dataclasses.fields(dataclass_type):
                    if field_definition.name in kwargs:
                        value = kwargs[field_definition.name]
                    elif field_definition.default_factory is not dataclasses.MISSING:  # type: ignore
                        value = field_definition.default_factory()
                    elif field_definition.default is not dataclasses.MISSING:
                        value = field_definition.default
                    else:
                        value = None

                    object.__setattr__(self, field_definition.name, value)

                # Track explicit fields for downstream logic that inspects this flag
                object.__setattr__(self, '_explicitly_set_fields', set(kwargs.keys()))

            return patched_init

        # Apply the patch
        lazy_type.__init__ = create_patched_init(lazy_type)

    try:
        yield
    finally:
        # Restore original constructors
        for lazy_type, original_init in original_constructors.items():
            lazy_type.__init__ = original_init


# Generic utility functions for clean thread-local storage management
def ensure_global_config_context(global_config_type: Type, global_config_instance: Any) -> None:
    """Ensure proper thread-local storage setup for any global config type."""
    from objectstate.global_config import set_global_config_for_editing
    set_global_config_for_editing(global_config_type, global_config_instance)


# ContextProvider infrastructure removed - was dead code feeding broken frame.f_locals manipulation




def resolve_lazy_configurations_for_serialization(data: Any) -> Any:
    """
    Recursively resolve lazy dataclass instances to concrete values for serialization.

    CRITICAL: This function must be called WITHIN a config_context() block!
    The context provides the hierarchy for lazy resolution.

    How it works:
    1. For lazy dataclasses: Access fields with getattr() to trigger resolution
    2. The lazy __getattribute__ uses the active config_context() to resolve None values
    3. Convert resolved values to base config for pickling

    Example (from README.md):
        with config_context(orchestrator.pipeline_config):
            # Lazy resolution happens here via context
            resolved_steps = resolve_lazy_configurations_for_serialization(steps)
    """
    # Check if this is a lazy dataclass
    base_type = get_base_type_for_lazy(type(data))
    if base_type is not None:
        # This is a lazy dataclass - resolve fields using getattr() within the active context
        # getattr() triggers lazy __getattribute__ which uses config_context() for resolution
        resolved_fields = {}
        for f in fields(data):
            # CRITICAL: Use getattr() to trigger lazy resolution via context
            # The active config_context() provides the hierarchy for resolution
            resolved_value = getattr(data, f.name)
            resolved_fields[f.name] = resolved_value

        # Create base config instance with resolved values
        resolved_data = base_type(**resolved_fields)
    else:
        # Not a lazy dataclass
        resolved_data = data

    # Recursively process nested structures based on type
    if is_dataclass(resolved_data) and not isinstance(resolved_data, type):
        # Process dataclass fields recursively
        logger.debug(f"Resolving fields for {type(resolved_data).__name__}: {[f.name for f in fields(resolved_data)]}")
        resolved_fields = {}
        for f in fields(resolved_data):
            field_value = getattr(resolved_data, f.name)
            logger.debug(f"Resolving {type(resolved_data).__name__}.{f.name} = {type(field_value).__name__}")
            resolved_fields[f.name] = resolve_lazy_configurations_for_serialization(field_value)
        cls = type(resolved_data)

        # Optional hook: allow dataclasses with custom constructors to control rebuild.
        rebuild = getattr(cls, "__objectstate_rebuild__", None)
        if callable(rebuild):
            return rebuild(**resolved_fields)

        # Default: try normal construction, then fall back to field-wise construction.
        try:
            return cls(**resolved_fields)
        except TypeError:
            obj = cls.__new__(cls)
            for k, v in resolved_fields.items():
                object.__setattr__(obj, k, v)
            return obj

    elif isinstance(resolved_data, dict):
        # Process dictionary values recursively
        return {
            key: resolve_lazy_configurations_for_serialization(value)
            for key, value in resolved_data.items()
        }

    elif isinstance(resolved_data, (list, tuple)):
        # Process sequence elements recursively
        resolved_items = [resolve_lazy_configurations_for_serialization(item) for item in resolved_data]
        return type(resolved_data)(resolved_items)

    else:
        # Primitive type or unknown structure - return as-is
        return resolved_data


# Generic dataclass editing with configurable value preservation
T = TypeVar('T')


def create_dataclass_for_editing(dataclass_type: Type[T], source_config: Any, preserve_values: bool = False, context_provider: Optional[Callable[[Any], None]] = None) -> T:
    """Create dataclass for editing with configurable value preservation."""
    if not is_dataclass(dataclass_type):
        raise ValueError(f"{dataclass_type} must be a dataclass")

    # Set up context if provider is given (e.g., thread-local storage)
    if context_provider:
        context_provider(source_config)

    field_values = {
        f.name: (getattr(source_config, f.name) if preserve_values
                else f.type() if is_dataclass(f.type) and has_lazy_resolution(f.type)
                else None)
        for f in fields(dataclass_type)
    }

    return dataclass_type(**field_values)





def rebuild_lazy_config_with_new_global_reference(
    existing_lazy_config: Any,
    new_global_config: Any,
    global_config_type: Optional[Type] = None
) -> Any:
    """
    Rebuild lazy config to reference new global config while preserving field states.

    This function preserves the exact field state of the existing lazy config:
    - Fields that are None (using lazy resolution) remain None
    - Fields that have been explicitly set retain their concrete values
    - Nested dataclass fields are recursively rebuilt to reference new global config
    - The underlying global config reference is updated for None field resolution

    Args:
        existing_lazy_config: Current lazy config instance
        new_global_config: New global config to reference for lazy resolution
        global_config_type: Type of the global config (defaults to type of new_global_config)

    Returns:
        New lazy config instance with preserved field states and updated global reference
    """
    if existing_lazy_config is None:
        return None

    # Determine global config type
    if global_config_type is None:
        global_config_type = type(new_global_config)

    # Set new global config in thread-local storage
    ensure_global_config_context(global_config_type, new_global_config)

    # Extract current field values without triggering lazy resolution - inline field processing pattern
    def process_field_value(field_obj):
        raw_value = object.__getattribute__(existing_lazy_config, field_obj.name)

        if raw_value is not None and hasattr(raw_value, '__dataclass_fields__'):
            try:
                # Rebuild nested dataclass recursively
                # Decorated config types declare lazy resolution nominally.
                nested_result = rebuild_lazy_config_with_new_global_reference(raw_value, new_global_config, global_config_type)
                return nested_result
            except Exception as e:
                logger.debug(f"Failed to rebuild nested config {field_obj.name}: {e}")
                return raw_value
        return raw_value

    current_field_values = {f.name: process_field_value(f) for f in fields(existing_lazy_config)}

    return type(existing_lazy_config)(**current_field_values)


# Declarative Global Config Field Injection System
# Moved inline imports to top-level

# Naming configuration
GLOBAL_CONFIG_PREFIX = "Global"
LAZY_CONFIG_PREFIX = "Lazy"

# Registry to accumulate all decorations before injection
_pending_injections = {}

# Preview label registry: Type -> label string
# Used by UI to auto-discover which configs should appear in list item previews
PREVIEW_LABEL_REGISTRY: Dict[Type, str] = {}

# Field abbreviations registry: Type -> {field_name: abbreviation}
# Used by UI to display compact field names in list item previews
FIELD_ABBREVIATIONS_REGISTRY: Dict[Type, Dict[str, str]] = {}

# Group abbreviations registry: Type -> abbreviation string
# Used by UI to display compact config class names in grouped previews
GROUP_ABBREVIATIONS_REGISTRY: Dict[Type, str] = {}

# Always viewable fields registry: Type -> List[field_name]
# Used by UI to auto-discover which fields should always be shown in list item previews
# regardless of the specific widget's PREVIEW_FIELD_CONFIGS.
# This allows config types to declare their own preview fields declaratively.
ALWAYS_VIEWABLE_FIELDS_REGISTRY: Dict[Type, List[str]] = {}


class abbreviation:
    """
    Decorator/marker for abbreviations in config classes.

    Can be used as:
    1. Class decorator: @abbreviation('wfc') to set class abbreviation
    2. In Annotated types: Annotated[Type, abbreviation('wf')] for field abbreviation

    Examples:
        @abbreviation('wfc')
        @global_pipeline_config
        @dataclass
        class WellFilterConfig:
            well_filter: Annotated[Optional[int], abbreviation('wf')] = None
            well_filter_mode: Annotated[WellFilterMode, abbreviation('wfm')] = WellFilterMode.INCLUDE

    Args:
        name: The abbreviation string

    Returns:
        When used as class decorator: the class with _abbreviation attribute set
        When used in Annotated: a marker object storing the abbreviation
    """

    def __init__(self, name: str):
        self.name = name

    def __call__(self, cls: Type) -> Type:
        """Class decorator usage: @abbreviation('wfc')"""
        cls._abbreviation = self.name
        # CRITICAL: Register immediately so @global_pipeline_config detects the correct value.
        # Decorators apply bottom-up, so @abbreviation runs AFTER @global_pipeline_config.
        # Without this, @global_pipeline_config would see the parent's _abbreviation.
        GROUP_ABBREVIATIONS_REGISTRY[cls] = self.name
        
        # Also update the lazy wrapper class if it exists
        # The lazy wrapper is created by @global_pipeline_config before @abbreviation runs,
        # so we need to update its abbreviation here to keep them in sync.
        lazy_class_name = f"{LAZY_CONFIG_PREFIX}{cls.__name__}"
        lazy_class = getattr(sys.modules[cls.__module__], lazy_class_name, None)
        if lazy_class is not None:
            GROUP_ABBREVIATIONS_REGISTRY[lazy_class] = self.name
            logger.debug(f"🔍 @abbreviation: Updated lazy wrapper {lazy_class_name} -> {self.name}")
        
        return cls

    def __repr__(self) -> str:
        return f"abbreviation({self.name!r})"


def _extract_abbreviations_from_annotations(cls: Type) -> Dict[str, str]:
    """
    Extract field abbreviations from Annotated type hints.
    
    Scans class annotations for fields using Annotated[..., abbreviation('...')]
    and returns a dict mapping field names to abbreviations.
    
    Walks the MRO from most-specific to least-specific, so child class
    annotations override parent class annotations (provenance wins).
    
    Args:
        cls: The class to scan
        
    Returns:
        Dict mapping field names to abbreviation strings
    """
    from typing import get_origin, get_args
    
    field_abbreviations = {}
    
    # Walk MRO from most-specific to least-specific
    # This ensures child class annotations override parent class annotations
    for klass in cls.__mro__:
        if klass is object:
            continue
            
        # Get this class's own annotations (not inherited)
        annotations = klass.__dict__.get('__annotations__', {})
        
        for field_name, field_type in annotations.items():
            # Check if this is an Annotated type
            origin = get_origin(field_type)
            if origin is not None:
                # Get the args - first is the actual type, rest are metadata
                args = get_args(field_type)
                if len(args) > 1:
                    # Check metadata for abbreviation markers
                    for metadata in args[1:]:
                        if isinstance(metadata, abbreviation):
                            # Child class definitions override parent class
                            # because we walk MRO most-specific first
                            field_abbreviations[field_name] = metadata.name
                            break
    
    return field_abbreviations


def get_group_abbreviation(config_type: Union[str, type]) -> str:
    """Look up group abbreviation from GROUP_ABBREVIATIONS_REGISTRY.

    Handles both type objects and type name strings.

    Args:
        config_type: Config class or type name to get abbreviation for

    Returns:
        Abbreviation string if found, otherwise falls back to class name prefix
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if isinstance(config_type, str):
        return config_type.split('_')[0] if config_type else "root"

    # Debug: Log lookup attempt
    logger.debug(f"🔍 get_group_abbreviation: looking up {config_type.__name__}")
    logger.debug(f"🔍   MRO: {[c.__name__ for c in config_type.__mro__]}")
    logger.debug(f"🔍   Registry keys: {[k.__name__ if hasattr(k, '__name__') else str(k) for k in GROUP_ABBREVIATIONS_REGISTRY.keys()]}")

    if config_type in GROUP_ABBREVIATIONS_REGISTRY:
        abbr = GROUP_ABBREVIATIONS_REGISTRY[config_type]
        logger.debug(f"🔍   Found direct: {abbr}")
        return abbr

    for base in config_type.__mro__[1:]:
        if base in GROUP_ABBREVIATIONS_REGISTRY:
            abbr = GROUP_ABBREVIATIONS_REGISTRY[base]
            logger.debug(f"🔍   Found in MRO {base.__name__}: {abbr}")
            return abbr

    fallback = config_type.__name__.split('_')[0]
    logger.debug(f"🔍   Fallback: {fallback}")
    return fallback


def create_global_default_decorator(target_config_class: Type):
    """
    Create a decorator factory for a specific global config class.

    The decorator accumulates all decorations, then injects all fields at once
    when the module finishes loading. Also creates lazy versions of all decorated configs.
    """
    target_class_name = target_config_class.__name__
    if target_class_name not in _pending_injections:
        _pending_injections[target_class_name] = {
            'target_class': target_config_class,
            'configs_to_inject': []
        }

    def global_default_decorator(cls=None, *, optional: bool = False, inherit_as_none: bool = True, ui_hidden: bool = False, preview_label: Optional[str] = None, abbreviation: Optional[str] = None, field_abbreviations: Optional[Dict[str, str]] = None, always_viewable_fields: Optional[List[str]] = None):
        """
        Decorator that can be used with or without parameters.

        Args:
            cls: The class being decorated (when used without parentheses)
            optional: Whether to wrap the field type with Optional (default: False)
            inherit_as_none: Whether to set all inherited fields to None by default (default: True)
            ui_hidden: Whether to hide from UI (apply decorator but don't inject into global config) (default: False)
            preview_label: Short label for list item previews (e.g., "NAP", "FIJI", "MAT"). If set,
                          config will appear in preview when enabled. Registered in PREVIEW_LABEL_REGISTRY.
            abbreviation: Short abbreviation for config class name used in grouped previews (e.g., "pp" for PathPlanningConfig).
                         Registered in GROUP_ABBREVIATIONS_REGISTRY.
            field_abbreviations: Dict mapping field names to abbreviations for compact display.
                          E.g., {'well_filter': 'wf', 'num_workers': 'W'}. Registered in FIELD_ABBREVIATIONS_REGISTRY.
            always_viewable_fields: List of field names that should always be shown in list item previews
                          for this config type. E.g., ['enabled', 'persistent']. Registered in ALWAYS_VIEWABLE_FIELDS_REGISTRY.
        """
        def decorator(actual_cls):
            # UNIFIED NONE-FORCING: Single make_dataclass rebuild instead of old 3-stage approach
            if inherit_as_none:
                # Rebuild class with None defaults for inherited fields
                # This replaces the old pre-process setattr + post-process Field patching
                inherited_fields = get_inherited_field_names(actual_cls)
                if inherited_fields:
                    actual_cls = rebuild_with_none_defaults(actual_cls, inherited_fields)

            # Generate field and class names
            field_name = _camel_to_snake(actual_cls.__name__)
            lazy_class_name = f"{LAZY_CONFIG_PREFIX}{actual_cls.__name__}"

            # Mark class with typed ui_hidden metadata for UI layer to check
            # This allows the config to remain in the context (for lazy resolution)
            # while being hidden from UI rendering
            if ui_hidden:
                mark_ui_hidden_config(actual_cls)

            # Register preview label for UI list item previews
            # Allows ABC to auto-discover which configs should appear in preview
            if preview_label is not None:
                PREVIEW_LABEL_REGISTRY[actual_cls] = preview_label

            # Register group abbreviation for config class name in grouped previews
            # Priority: explicit parameter > @abbreviation decorator > auto-generated
            detected_class_abbr = getattr(actual_cls, '_abbreviation', None)
            final_class_abbr = abbreviation or detected_class_abbr
            logger.debug(f"🔍 @global_pipeline_config: {actual_cls.__name__} - detected={detected_class_abbr}, explicit={abbreviation}, final={final_class_abbr}")
            if final_class_abbr is not None:
                GROUP_ABBREVIATIONS_REGISTRY[actual_cls] = final_class_abbr
                logger.debug(f"🔍   Registered {actual_cls.__name__} -> {final_class_abbr}")

            # Register field abbreviations for compact preview display
            # Priority: explicit parameter > @abbreviation in Annotated types
            detected_field_abbrs = _extract_abbreviations_from_annotations(actual_cls)
            final_field_abbrs = {**detected_field_abbrs, **(field_abbreviations or {})}
            logger.debug(f"🔍   Field abbrs detected={detected_field_abbrs}, explicit={field_abbreviations}, final={final_field_abbrs}")
            if final_field_abbrs:
                FIELD_ABBREVIATIONS_REGISTRY[actual_cls] = final_field_abbrs

            # Register always viewable fields for this config type
            # These fields will always be shown in list item previews regardless of widget config
            if always_viewable_fields:
                ALWAYS_VIEWABLE_FIELDS_REGISTRY[actual_cls] = always_viewable_fields
                logger.debug(f"🔍   Registered always_viewable_fields for {actual_cls.__name__}: {always_viewable_fields}")

            # Check if class is abstract (has unimplemented abstract methods)
            # Abstract classes should NEVER be injected into GlobalPipelineConfig
            # because they can't be instantiated
            # NOTE: We need to check if the class ITSELF is abstract, not just if it inherits from ABC
            # Concrete subclasses of abstract classes should still be injected
            # We check for __abstractmethods__ attribute which exists even before @dataclass runs
            # (it's set by ABCMeta when the class is created)
            is_abstract = hasattr(actual_cls, '__abstractmethods__') and len(actual_cls.__abstractmethods__) > 0

            # Add to pending injections for field injection
            # Skip injection for abstract classes (they can't be instantiated)
            # For concrete classes: inject even if ui_hidden (needed for lazy resolution context)
            if not is_abstract:
                _pending_injections[target_class_name]['configs_to_inject'].append({
                    'config_class': actual_cls,
                    'field_name': field_name,
                    'lazy_class_name': lazy_class_name,
                    'optional': optional,  # Store the optional flag
                    'inherit_as_none': inherit_as_none,  # Store the inherit_as_none flag
                    'ui_hidden': ui_hidden  # Store the ui_hidden flag for field metadata
                })

            # Immediately create lazy version of this config (not dependent on injection)


            # Declare contextual resolution on the concrete type before deriving
            # its lazy form. The nominal relationship, not a marker attribute,
            # is the capability contract used by the factory and its consumers.
            bind_lazy_resolution_to_class(actual_cls)

            lazy_class = LazyDataclassFactory.make_lazy_simple(
                base_class=actual_cls,
                lazy_class_name=lazy_class_name
            )

            # Export lazy class to config module immediately
            config_module = sys.modules[actual_cls.__module__]
            setattr(config_module, lazy_class_name, lazy_class)

            # Copy metadata to lazy class for UI compatibility
            if ui_hidden:
                mark_ui_hidden_config(lazy_class)
            if preview_label is not None:
                PREVIEW_LABEL_REGISTRY[lazy_class] = preview_label
            # Copy class abbreviation to lazy class
            # Priority: 1. explicit param, 2. registry lookup (set by @abbreviation), 3. detected from class
            class_abbr_to_copy = abbreviation or GROUP_ABBREVIATIONS_REGISTRY.get(actual_cls) or detected_class_abbr
            if class_abbr_to_copy is not None:
                GROUP_ABBREVIATIONS_REGISTRY[lazy_class] = class_abbr_to_copy
            # Copy field abbreviations to lazy class (from explicit param or detected from Annotated)
            field_abbr_to_copy = field_abbreviations or detected_field_abbrs
            if field_abbr_to_copy:
                FIELD_ABBREVIATIONS_REGISTRY[lazy_class] = field_abbr_to_copy

            # Copy always_viewable_fields to lazy class
            if always_viewable_fields:
                ALWAYS_VIEWABLE_FIELDS_REGISTRY[lazy_class] = always_viewable_fields

            # Note: No Stage 3 post-processing needed!
            # - Base class: rebuilt via rebuild_with_none_defaults() above
            # - Lazy class: _introspect_dataclass_fields() already sets None defaults

            return actual_cls

        # Handle both @decorator and @decorator() usage
        if cls is None:
            # Called with parentheses: @decorator(optional=True)
            return decorator
        else:
            # Called without parentheses: @decorator
            return decorator(cls)

    return global_default_decorator


def _inject_all_pending_fields():
    """Inject all accumulated fields at once."""
    for target_name, injection_data in _pending_injections.items():
        target_class = injection_data['target_class']
        configs = injection_data['configs_to_inject']

        if configs:  # Only inject if there are configs to inject
            _inject_multiple_fields_into_dataclass(target_class, configs)

def _camel_to_snake(name: str) -> str:
    """Convert CamelCase to snake_case for field names."""
    s1 = re.sub('(.)([A-Z][a-z]+)', r'\1_\2', name)
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', s1).lower()

def _inject_multiple_fields_into_dataclass(target_class: Type, configs: List[Dict]) -> None:
    """Mathematical simplification: Batch field injection with direct dataclass recreation."""
    # Imports moved to top-level

    # Direct field reconstruction - guaranteed by dataclass contract
    existing_fields = [
        (f.name, f.type, field(default_factory=f.default_factory) if f.default_factory != MISSING
         else f.default if f.default != MISSING else f.type)
        for f in fields(target_class)
    ]

    # Mathematical simplification: Unified field construction with algebraic common factors
    def create_field_definition(config):
        """Create field definition with optional and inherit_as_none support."""
        field_type = config['config_class']
        is_optional = config.get('optional', False)
        is_ui_hidden = config.get('ui_hidden', False)

        # Algebraic simplification: factor out common default_value logic
        if is_optional:
            field_type = Union[field_type, type(None)]
            default_value = None
        else:
            # CRITICAL: GlobalPipelineConfig needs default_factory to create instances with defaults
            # PipelineConfig (created by make_lazy_simple) automatically gets default=None
            # So we use default_factory here for GlobalPipelineConfig fields
            default_value = field(default_factory=field_type, metadata={'ui_hidden': is_ui_hidden})

        return (config['field_name'], field_type, default_value)

    all_fields = existing_fields + [create_field_definition(config) for config in configs]

    # Direct dataclass recreation - fail-loud
    new_class = make_dataclass(
        target_class.__name__,
        all_fields,
        bases=target_class.__bases__,
        frozen=target_class.__dataclass_params__.frozen
    )

    # CRITICAL: Preserve original module for proper imports in generated code
    # make_dataclass() sets __module__ to the caller's module (lazy_factory.py)
    # We need to set it to the target class's original module for correct import paths
    new_class.__module__ = target_class.__module__


    # Preserve global-config registration across dataclass recreation.
    # Registration is set by @auto_create_decorator but lost when make_dataclass creates a new class.
    if is_global_config_type(target_class):
        mark_global_config_type(new_class)
    # Sibling inheritance is now handled by the dual-axis resolver system

    # Direct module replacement
    module = sys.modules[target_class.__module__]
    setattr(module, target_class.__name__, new_class)
    globals()[target_class.__name__] = new_class

    # Mathematical simplification: Extract common module assignment pattern
    def _register_lazy_class(lazy_class, class_name, module_name):
        """Register lazy class in both module and global namespace."""
        setattr(sys.modules[module_name], class_name, lazy_class)
        globals()[class_name] = lazy_class

    # Create lazy classes and recreate PipelineConfig inline
    for config in configs:
        lazy_class = LazyDataclassFactory.make_lazy_simple(
            base_class=config['config_class'],
            lazy_class_name=config['lazy_class_name']
        )
        _register_lazy_class(lazy_class, config['lazy_class_name'], config['config_class'].__module__)

    # Create lazy version of the updated global config itself with proper naming
    # Global configs must start with GLOBAL_CONFIG_PREFIX - fail-loud if not
    if not target_class.__name__.startswith(GLOBAL_CONFIG_PREFIX):
        raise ValueError(f"Target class '{target_class.__name__}' must start with '{GLOBAL_CONFIG_PREFIX}' prefix")

    # Remove global prefix (GlobalPipelineConfig → PipelineConfig)
    lazy_global_class_name = target_class.__name__[len(GLOBAL_CONFIG_PREFIX):]

    lazy_global_class = LazyDataclassFactory.make_lazy_simple(
        base_class=new_class,
        lazy_class_name=lazy_global_class_name
    )

    # Use extracted helper for consistent registration
    _register_lazy_class(lazy_global_class, lazy_global_class_name, target_class.__module__)





def auto_create_decorator(global_config_class):
    """
    Decorator that automatically creates:
    1. A field injection decorator for other configs to use
    2. A lazy version of the global config itself

    Global config classes must start with "Global" prefix.
    """
    # Validate naming convention
    if not global_config_class.__name__.startswith(GLOBAL_CONFIG_PREFIX):
        raise ValueError(f"Global config class '{global_config_class.__name__}' must start with '{GLOBAL_CONFIG_PREFIX}' prefix")

    # Mark this class as a global config for isinstance checks via GlobalConfigBase.
    mark_global_config_type(global_config_class)

    decorator_name = _camel_to_snake(global_config_class.__name__)
    decorator = create_global_default_decorator(global_config_class)

    # Export decorator to module globals
    module = sys.modules[global_config_class.__module__]
    setattr(module, decorator_name, decorator)

    # Lazy global config will be created after field injection

    return global_config_class
