"""Generic lazy dataclass factory using flexible resolution."""

# Standard library imports
import copy
import dataclasses
import inspect
import logging
import re
import sys
from abc import ABC
from contextlib import contextmanager
from objectstate.field_value import FieldValue, Inherit, Unset
from objectstate.field_access import DataclassFieldAccess
from objectstate.declarations import ValueDeclaration, InheritedDefault, ValueDefault, FactoryDefault, admit_root_value
from objectstate.dual_axis_resolver import resolve_with_provenance
from objectstate.construction_binding import admit_target
from dataclasses import MISSING, dataclass, field, fields, make_dataclass
from functools import lru_cache
from typing import Annotated, Any, Callable, Dict, List, Optional, Tuple, Type, TypeVar, Union, get_type_hints, get_args, get_origin

from python_introspect import (
    make_optional,
    register_type_resolver,
    resolve_annotated,
    resolve_optional,
)

from objectstate.ui_visibility import mark_ui_hidden_config, UIParameterVisibilityPolicy
from python_introspect import resolve_declared_type

# Note: dual_axis_resolver_recursive and lazy_placeholder imports kept inline to avoid circular imports


# Type registry for lazy dataclass to base class mapping
_lazy_type_registry: Dict[Type, Type] = {}

# Reverse registry for base class to lazy dataclass mapping (for O(1) lookup)
_base_to_lazy_registry: Dict[Type, Type] = {}




def _recreated_dataclass_namespace(
    declared_type: type,
    recreated_name: str,
) -> dict[str, object]:
    """Return declaration-owned metadata for a recreated dataclass.

    The module and qualified name are in the namespace so the class has them
    while it is being created: a metaclass that registers classes then sees the
    declaration the class was rebuilt from, not ``abc`` or this module.
    """

    namespace: dict[str, object] = {
        "__doc__": declared_type.__doc__,
        "__module__": declared_type.__module__,
    }
    if recreated_name == declared_type.__name__:
        namespace["__qualname__"] = declared_type.__qualname__
    return namespace


def _restore_recreated_dataclass_metadata(
    recreated_type: type,
    declared_type: type,
) -> type:
    """Restore runtime metadata that class creation may replace or remove."""

    recreated_type.__module__ = declared_type.__module__
    recreated_type.__doc__ = declared_type.__doc__
    if recreated_type.__name__ == declared_type.__name__:
        recreated_type.__qualname__ = declared_type.__qualname__

    declared_first_line = declared_type.__dict__.get("__firstlineno__", MISSING)
    if declared_first_line is not MISSING:
        try:
            setattr(recreated_type, "__firstlineno__", declared_first_line)
        except (AttributeError, TypeError):
            pass
    return recreated_type


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
        for owner in ValueDeclaration.of(base).configuration_owners():
            parent_fields.update(item.name for item in owner.declared_fields())

    # cls's OWN annotations (not inherited). Python 3.14 (PEP 649) no longer
    # stores them in cls.__dict__['__annotations__'].
    own_defined = set(inspect.get_annotations(cls, eval_str=False))

    return parent_fields - own_defined


def _inheritance_metadata(field_definition) -> dict:
    """Preserve a declaration's one inherited-default member."""
    metadata = dict(field_definition.metadata)
    if InheritedDefault not in metadata:
        if field_definition.default is not MISSING:
            metadata[InheritedDefault] = ValueDefault(field_definition.default)
        elif field_definition.default_factory is not MISSING:
            metadata[InheritedDefault] = FactoryDefault(field_definition.default_factory)
    return metadata


def rebuild_with_inheritance(
    cls: Type,
    inherited_field_names: Optional[set] = None,
    new_name: Optional[str] = None
) -> Type:
    """
    Rebuild a dataclass via make_dataclass with None defaults for specified fields.

    This is the UNIFIED approach for both base classes (inherit_fields) and lazy classes.
    Instead of patching Field objects after @dataclass, we rebuild with correct defaults.

    Args:
        cls: The dataclass to rebuild
        inherited_field_names: Fields that should have default=None.
                            If None, ALL fields get default=None (for lazy classes).
        new_name: Optional new class name (for lazy classes)

    Returns:
        A new class with the same fields but modified defaults
    """
    declaration = ValueDeclaration.of(cls)
    declaration.require_config_type()

    if inherited_field_names is None:
        # All fields get None (for lazy classes)
        inherited_field_names = {f.name for f in fields(cls)}

    annotations = ValueDeclaration.of(cls).field_annotations()

    # Build field definitions
    field_defs = []
    for f in fields(cls):
        declared_type = annotations[f.name]
        if f.name in inherited_field_names:
            # Force None default, but preserve original default in metadata for fallback
            # This allows standalone usage to fall back to parent's static default
            field_defs.append(
                (
                    f.name,
                    declared_type,
                    field(
                        default=Inherit(),
                        metadata=_inheritance_metadata(f),
                    ),
                )
            )
        else:
            # Preserve original field (copy to avoid sharing)
            field_defs.append((f.name, declared_type, copy.copy(f)))

    # Collect non-dunder attributes to preserve (methods, class vars, etc.)
    recreated_name = new_name or cls.__name__
    namespace = _recreated_dataclass_namespace(cls, recreated_name)
    for key, value in cls.__dict__.items():
        if key.startswith('__') and key.endswith('__'):
            # Skip most dunders (make_dataclass will generate them)
            # BUT preserve lifecycle/registration declarations.
            if key not in {"__post_init__", "__registry_key__"}:
                continue
        if key == '__dataclass_fields__':
            continue  # Will be regenerated
        namespace[key] = value

    # Keep original bases for isinstance() to work
    bases = cls.__bases__

    # Check if any base is a frozen dataclass - if so, new class must also be frozen
    is_frozen = any(owner.frozen_declaration() for base in cls.__mro__[1:] for owner in ValueDeclaration.of(base).configuration_owners())

    # Get the original metaclass to preserve it
    orig_metaclass = type(cls)

    # Create new class
    new_cls = make_dataclass(
        recreated_name,
        fields=field_defs,
        bases=bases,
        namespace=namespace,
        frozen=is_frozen,
    )

    # make_dataclass takes no metaclass parameter: it derives one from the
    # bases. When the declared class names a metaclass its bases do not carry,
    # create the class once more with that metaclass. @dataclass is NOT
    # re-applied, since make_dataclass already did that.
    if type(new_cls) is not orig_metaclass:
        new_cls = orig_metaclass(
            new_cls.__name__,
            new_cls.__bases__,
            {**new_cls.__dict__, **_recreated_dataclass_namespace(cls, recreated_name)},
        )

    return _restore_recreated_dataclass_metadata(new_cls, cls)


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
    # Get all field values using object.__getattribute__ to avoid lazy resolution
    field_values = {}
    for f in fields(instance):
        if f.name in changes:
            field_values[f.name] = changes[f.name]
        else:
            # Use object.__getattribute__ to get raw value (bypass lazy __getattribute__)
            field_values[f.name] = DataclassFieldAccess.raw_value(instance, f.name)

    # Create new instance with raw values
    return type(instance)(**field_values)



def retain_only_authored_paths(value, authored_field_paths) -> Any:
    """Copy a lazy dataclass, marking only ``authored_field_paths`` as explicitly set.

    An ObjectState rebuild constructs every nested lazy dataclass from all its
    flattened fields, so every constructor keyword reads as explicit. Clean
    source generation needs the authored paths ObjectState already tracks
    (its signature-diff fields); this applies them to the lazy metadata without
    changing any field value.
    """

    from objectstate.field_access import DottedFieldPath

    paths = tuple(DottedFieldPath(path) for path in authored_field_paths)
    return _copy_with_only_authored_paths(value, DottedFieldPath(""), paths)


def _copy_with_only_authored_paths(value, prefix, authored_field_paths):
    from objectstate.field_access import DataclassFieldAccess

    field_values = {}
    for field_definition in fields(value):
        field_value = DataclassFieldAccess.raw_value(value, field_definition.name)
        if isinstance(field_value, LazyDataclass):
            field_value = _copy_with_only_authored_paths(
                field_value,
                prefix.child(field_definition.name),
                authored_field_paths,
            )
        field_values[field_definition.name] = field_value

    projected = type(value)(**field_values)
    object.__setattr__(
        projected,
        "_explicitly_set_fields",
        {
            field_definition.name
            for field_definition in fields(projected)
            if prefix.child(field_definition.name).contains_any(authored_field_paths)
        },
    )
    return projected

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
    ValueDeclaration.of(config_type).require_config_type()
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
    - LazyPartitionFilterConfig
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






def _single_declared_config_field(
    owner_type: type,
    config_type: type,
    *,
    required: bool,
) -> Optional[str]:
    """Select one annotation-owned config field and reject ambiguity."""

    owner = ValueDeclaration.of(owner_type)
    owner.require_config_type()
    config_base = resolve_declared_type(config_type)
    field_names = tuple(
        name for name, declared_type in owner.configuration_fields()
        if (resolve_declared_type(declared_type)) is config_base
    )
    if len(field_names) == 1:
        return field_names[0]
    if not field_names and not required:
        return None
    config_base = resolve_declared_type(config_type)
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



def bind_lazy_resolution_to_class(cls: Type) -> None:
    """
    Add lazy __getattribute__ to an existing class.

    This enables concrete classes (like PartitionFilterConfig stored in
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
        """Create the method that resolves one field in the active context."""
        from objectstate.dual_axis_resolver import resolve_with_provenance

        def _resolve_field_value(self, field_name: str) -> Any:
            return resolve_with_provenance(type(self), field_name).value

        return _resolve_field_value

    @staticmethod
    def create_getattribute() -> Callable[[Any, str], Any]:
        """Create lazy __getattribute__: a None field reads its value from the active context."""
        from objectstate.context_manager import context_layer_stack
        from objectstate.dual_axis_resolver import declared_default, resolve_in_stack

        def __getattribute__(self: Any, name: str) -> Any:
            value = object.__getattribute__(self, name)
            # Fast path: non-None values never need resolution
            if not FieldValue.of(value).inherits():
                return value
            # PERFORMANCE: Use pre-computed frozenset (O(1) lookup) instead of
            # rebuilding {f.name for f in fields(self.__class__)} (O(n)) on every access.
            # Use object.__getattribute__ for __class__ to avoid recursion.
            # Lazily populate if not yet set (e.g. class created outside _create_lazy_dataclass_unified).
            _cls = object.__getattribute__(self, '__class__')
            _fns = _cls.__dict__.get('_field_names_set')
            if _fns is None:
                _ft = fields(_cls)
                _fns = frozenset(f.name for f in _ft)
                _cls._field_names_set = _fns
                _cls._fields_by_name = {f.name: f for f in _ft}
            if name not in _fns:
                return value

            stack = context_layer_stack.get()
            if not stack.layers:
                return declared_default(_cls, name)[0]
            return value.resolve(lambda: FieldValue.of(resolve_in_stack(stack, _cls, name).value)).stored

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
            field_values = {f.name: DataclassFieldAccess.raw_value(self, f.name) for f in fields(self)}
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
                    value = DataclassFieldAccess.raw_value(config, field_definition.name)
                    if inherited is not None and value == DataclassFieldAccess.raw_value(inherited, field_definition.name):
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

    @classmethod
    def configuration_field(cls, owner, declaration, annotation):
        declared_type = owner.declaring_type
        lazy_type = declared_type if resolve_declared_type(declared_type) is not declared_type else get_lazy_type_for_base(declared_type)
        if lazy_type is None:
            if not has_lazy_resolution(declared_type):
                return ValueDeclaration.lazy_field(owner, declaration, annotation, cls)
            lazy_type = cls.make_lazy_simple(declared_type)
        transformed = Annotated[lazy_type, *get_args(annotation)[1:]] if get_origin(annotation) is Annotated else lazy_type
        return transformed, field(default_factory=lazy_type, metadata=declaration.metadata)

    @staticmethod
    def configuration_editing_default(owner):
        return owner.admit_data(owner.declaring_type()) if has_lazy_resolution(owner.declaring_type) else Inherit()

    @staticmethod
    def registered_type_pairs() -> tuple[tuple[type, type], ...]:
        """Project current lazy/public declarations without constructing values."""
        return tuple(_lazy_type_registry.items())





    @classmethod
    def _introspect_dataclass_fields(cls, base, debug_template):
        """Declaration members produce their field definition, not type flags."""
        annotations = base.field_annotations()
        definitions = []
        for declaration in base.declared_fields():
            annotation = annotations[declaration.name]
            final_type, field_definition = ValueDeclaration.of(resolve_annotated(annotation)).lazy_field(declaration, annotation, cls)
            definitions.append((declaration.name, final_type, field_definition))
            logger.debug(debug_template.format(
                field_name=declaration.name,
                original_type=declaration.type,
                has_default=(declaration.default is not MISSING or declaration.default_factory is not MISSING),
                final_type=final_type,
            ))
        return definitions

    @staticmethod
    def _create_lazy_dataclass_unified(
        base_class: Type,
        lazy_class_name: str | None,
        debug_template: str,
    ) -> Type:
        """
        Create lazy dataclass with declarative configuration.

        Core factory method that creates lazy dataclass with introspected fields,
        binds resolution methods, and registers type mappings. Complex orchestration
        of field analysis, method binding, and class creation.
        """
        declaration = ValueDeclaration.of(base_class)
        declaration.require_config_type()

        registered_type = get_lazy_type_for_base(base_class)
        if registered_type is not None:
            if lazy_class_name not in (None, registered_type.__name__):
                raise ValueError(
                    f"{base_class.__name__} already owns lazy type "
                    f"{registered_type.__name__}; cannot also create "
                    f"{lazy_class_name}."
                )
            return registered_type
        if lazy_class_name is None:
            lazy_class_name = f"{LAZY_CLASS_NAME_PREFIX}{base_class.__name__}"

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
        base_is_frozen = declaration.frozen_declaration()

        # Single make_dataclass call - no duplication
        lazy_class = make_dataclass(
            lazy_class_name,
            LazyDataclassFactory._introspect_dataclass_fields(
                declaration,
                debug_template,
            ),
            bases=bases,
            namespace=_recreated_dataclass_namespace(
                base_class,
                lazy_class_name,
            ),
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

        _restore_recreated_dataclass_metadata(lazy_class, base_class)

        # Automatically register the lazy dataclass with the type registry
        register_lazy_type_mapping(lazy_class, base_class)

        return lazy_class





    @staticmethod
    def make_lazy_simple(
        base_class: Type,
        lazy_class_name: str | None = None
    ) -> Type:
        """
        Create lazy dataclass using new contextvars system.

        SIMPLIFIED: No complex hierarchy providers or field path detection needed.
        Uses new contextvars system for all resolution.

        Args:
            base_class: Base dataclass to make lazy
            lazy_class_name: Name for the lazy class. When omitted the factory
                names it, or returns the lazy class the base already owns.

        Returns:
            Generated lazy dataclass with contextvars-based resolution
        """
        return LazyDataclassFactory._create_lazy_dataclass_unified(
            base_class=base_class,
            lazy_class_name=lazy_class_name,
            debug_template=f"Simple contextvars resolution for {base_class.__name__}",
        )

    # All legacy methods removed - use make_lazy_simple() for all use cases


# =============================================================================
# Constructor Patching for Code Execution
# =============================================================================




# ContextProvider infrastructure removed - was dead code feeding broken frame.f_locals manipulation




def resolve_lazy_configurations_for_serialization(data: Any) -> Any:
    """Admit one input graph; members own recursive resolution and reconstruction.

    Inheritance requests require an active configuration context. Constructor
    failures propagate; serialization never bypasses a domain constructor.
    """
    return admit_root_value(data).for_serialization(resolve_with_provenance)


# Generic dataclass editing with configurable value preservation
T = TypeVar('T')


def create_dataclass_for_editing(dataclass_type: Type[T], source_config: Any, preserve_values: bool = False, context_provider: Optional[Callable[[Any], None]] = None) -> T:
    """Preserve stored meanings, or create inherited drafts without inventing nulls."""
    declaration = ValueDeclaration.of(dataclass_type)
    constructor = declaration.require_config_type()
    if context_provider:
        context_provider(source_config)
    source = admit_target(source_config)
    annotations = declaration.field_annotations()
    values = {
        field.name: (source.read_raw(field.name) if preserve_values
                     else ValueDeclaration.of(annotations[field.name]).editing_default(LazyDataclassFactory))
        for field in declaration.declared_fields() if field.init
    }
    return constructor(**{name: member.stored for name, member in values.items()})





# Declarative Global Config Field Injection System
# Moved inline imports to top-level

# Naming configuration
GLOBAL_CONFIG_PREFIX = "Global"

# Registry to accumulate all decorations before injection
_pending_injections = {}

# Preview label registry: Type -> label string
# Used by UI to auto-discover which configs should appear in list item previews
PREVIEW_LABEL_REGISTRY: Dict[Type, str] = {}

# Field abbreviations registry: Type -> {field_name: abbreviation}
# Used by UI to display compact field names in list item previews
FIELD_ABBREVIATIONS_REGISTRY: Dict[Type, Dict[str, str]] = {}

# Class attribute holding a config class's own group abbreviation. The class
# is the only owner; get_group_abbreviation reads it on demand.
GROUP_ABBREVIATION_ATTRIBUTE = "_abbreviation"

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
    2. In Annotated types: Annotated[Type, abbreviation('pf')] for field abbreviation

    Examples:
        @abbreviation('wfc')
        @global_pipeline_config
        @dataclass
        class PartitionFilterConfig:
            partition_filter: Annotated[Optional[int], abbreviation('pf')] = None
            partition_filter_mode: Annotated[
                type[PartitionFilterMode], abbreviation('pfm')
            ] = IncludePartitions

    Args:
        name: The abbreviation string

    Returns:
        When used as class decorator: the class, declaring its group abbreviation
        When used in Annotated: a marker object storing the abbreviation
    """

    def __init__(self, name: str):
        self.name = name

    def __call__(self, cls: Type) -> Type:
        """Class decorator usage: @abbreviation('wfc')"""
        declare_group_abbreviation(cls, self.name)
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
        annotations = inspect.get_annotations(klass, eval_str=False)
        
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


def declare_group_abbreviation(config_type: type, name: str) -> None:
    """Declare a config class's own group abbreviation.

    A lazy class has no abbreviation of its own: the declaration lands on its
    base class. A second, different declaration for one class raises.
    """
    declaring_type = resolve_declared_type(config_type)
    declared = vars(declaring_type).get(GROUP_ABBREVIATION_ATTRIBUTE)
    if declared is not None and declared != name:
        raise ValueError(
            f"{declaring_type.__qualname__} already declares abbreviation "
            f"{declared!r}; cannot also declare {name!r}."
        )
    setattr(declaring_type, GROUP_ABBREVIATION_ATTRIBUTE, name)


def get_group_abbreviation(config_type: str | type) -> str:
    """Read a config class's group abbreviation from its declaration.

    A lazy class answers with its base class's declaration. A class with no
    declaration of its own answers with its nearest declaring ancestor, then
    with the prefix of its class name. A type name string answers with its
    prefix.
    """
    if isinstance(config_type, str):
        return config_type.split('_')[0] if config_type else "root"

    declaring_type = resolve_declared_type(config_type)
    for ancestor in declaring_type.__mro__:
        declared = vars(ancestor).get(GROUP_ABBREVIATION_ATTRIBUTE)
        if declared is not None:
            return declared
    return config_type.__name__.split('_')[0]


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

    def global_default_decorator(cls=None, *, optional: bool = False, inherit_fields: bool = True, ui_hidden: bool = False, preview_label: Optional[str] = None, abbreviation: Optional[str] = None, field_abbreviations: Optional[Dict[str, str]] = None, always_viewable_fields: Optional[List[str]] = None):
        """
        Decorator that can be used with or without parameters.

        Args:
            cls: The class being decorated (when used without parentheses)
            optional: Whether to wrap the field type with Optional (default: False)
            inherit_fields: Whether to set all inherited fields to None by default (default: True)
            ui_hidden: Whether to hide from UI (apply decorator but don't inject into global config) (default: False)
            preview_label: Short label for list item previews (e.g., "NAP", "FIJI", "MAT"). If set,
                          config will appear in preview when enabled. Registered in PREVIEW_LABEL_REGISTRY.
            abbreviation: Short abbreviation for config class name used in grouped previews (e.g., "pp" for PathPlanningConfig).
                         Declared on the class; see declare_group_abbreviation.
            field_abbreviations: Dict mapping field names to abbreviations for compact display.
                          E.g., {'partition_filter': 'pf', 'num_workers': 'W'}. Registered in
                              FIELD_ABBREVIATIONS_REGISTRY.
            always_viewable_fields: List of field names that should always be shown in list item previews
                          for this config type. E.g., ['enabled', 'persistent']. Registered in ALWAYS_VIEWABLE_FIELDS_REGISTRY.
        """
        def decorator(actual_cls):
            # UNIFIED NONE-FORCING: Single make_dataclass rebuild instead of old 3-stage approach
            if inherit_fields:
                # Rebuild class with None defaults for inherited fields
                # This replaces the old pre-process setattr + post-process Field patching
                inherited_fields = get_inherited_field_names(actual_cls)
                if inherited_fields:
                    actual_cls = rebuild_with_inheritance(actual_cls, inherited_fields)

            field_name = _camel_to_snake(actual_cls.__name__)

            # Mark class with typed ui_hidden metadata for UI layer to check
            # This allows the config to remain in the context (for lazy resolution)
            # while being hidden from UI rendering
            if ui_hidden:
                mark_ui_hidden_config(actual_cls)

            # Register preview label for UI list item previews
            # Allows ABC to auto-discover which configs should appear in preview
            if preview_label is not None:
                PREVIEW_LABEL_REGISTRY[actual_cls] = preview_label

            # The class owns its group abbreviation; @abbreviation writes the
            # same declaration, so the two decorators may come in either order.
            if abbreviation is not None:
                declare_group_abbreviation(actual_cls, abbreviation)

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
                    'optional': optional,  # Store the optional flag
                    'inherit_fields': inherit_fields,  # Store the inherit_fields flag
                    UIParameterVisibilityPolicy: ui_hidden
                })

            # Immediately create lazy version of this config (not dependent on injection)


            # Declare contextual resolution on the concrete type before deriving
            # its lazy form. The nominal relationship, not a marker attribute,
            # is the capability contract used by the factory and its consumers.
            bind_lazy_resolution_to_class(actual_cls)

            lazy_class = LazyDataclassFactory.make_lazy_simple(actual_cls)

            # Export lazy class to config module immediately
            config_module = sys.modules[actual_cls.__module__]
            setattr(config_module, lazy_class.__name__, lazy_class)

            # Copy metadata to lazy class for UI compatibility
            if ui_hidden:
                mark_ui_hidden_config(lazy_class)
            if preview_label is not None:
                PREVIEW_LABEL_REGISTRY[lazy_class] = preview_label
            # Copy field abbreviations to lazy class (from explicit param or detected from Annotated)
            field_abbr_to_copy = field_abbreviations or detected_field_abbrs
            if field_abbr_to_copy:
                FIELD_ABBREVIATIONS_REGISTRY[lazy_class] = field_abbr_to_copy

            # Copy always_viewable_fields to lazy class
            if always_viewable_fields:
                ALWAYS_VIEWABLE_FIELDS_REGISTRY[lazy_class] = always_viewable_fields

            # Note: No Stage 3 post-processing needed!
            # - Base class: rebuilt via rebuild_with_inheritance() above
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

    annotations = ValueDeclaration.of(target_class).field_annotations()
    existing_fields = [
        (f.name, annotations[f.name], copy.copy(f))
        for f in fields(target_class)
    ]

    # Mathematical simplification: Unified field construction with algebraic common factors
    def create_field_definition(config):
        """Create field definition with optional and inherit_fields support."""
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
            default_value = field(default_factory=field_type, metadata=UIParameterVisibilityPolicy.field_metadata(is_ui_hidden))

        return (config['field_name'], field_type, default_value)

    all_fields = existing_fields + [create_field_definition(config) for config in configs]

    # Direct dataclass recreation - fail-loud
    new_class = make_dataclass(
        target_class.__name__,
        all_fields,
        bases=target_class.__bases__,
        namespace=_recreated_dataclass_namespace(
            target_class,
            target_class.__name__,
        ),
        frozen=target_class.__dataclass_params__.frozen
    )

    _restore_recreated_dataclass_metadata(new_class, target_class)

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
        lazy_class = LazyDataclassFactory.make_lazy_simple(config['config_class'])
        _register_lazy_class(lazy_class, lazy_class.__name__, config['config_class'].__module__)

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
