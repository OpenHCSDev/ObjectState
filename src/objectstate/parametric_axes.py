"""
Parametric Axes Prototype - Arbitrary semantic axes for type construction.

This module extends Python's type() to support arbitrary axes beyond (B, S).
It's a proof-of-concept for PEP proposal: extending type() with **axes.

Core concepts:
- AxesBase: Base class enabling `class Foo(Base, axes={...})` syntax (PREFERRED)
- AxesMeta: Metaclass that stores arbitrary axes in __axes__
- axes_type(): Factory function mimicking extended type() signature
- @with_axes: Decorator for class definitions

Usage (class statement syntax - PREFERRED):
    from objectstate.parametric_axes import AxesBase

    class Step(AxesBase):
        pass

    class MyStep(Step, axes={"scope": "/pipeline/step_0", "registry": STEP_REGISTRY}):
        pass

    MyStep.__axes__  # {'scope': '/pipeline/step_0', 'registry': ...}

Usage (factory function):
    from objectstate.parametric_axes import axes_type

    MyStep = axes_type("MyStep", (Step,), {"process": fn},
                       scope="/pipeline/step_0",
                       registry=STEP_REGISTRY)

    MyStep.__axes__  # {"scope": "/pipeline/step_0", "registry": ...}

Usage (decorator - when base class can't be modified):
    from objectstate.parametric_axes import with_axes

    @with_axes(scope="/pipeline/step_0", registry=STEP_REGISTRY)
    class MyStep(Step):
        pass
"""

from typing import Dict, Any, Tuple, Optional, Type
from types import MappingProxyType
import weakref

# =============================================================================
# TYPE CACHE - Same pattern as reified_generics
# =============================================================================

_axes_cache: Dict[Tuple[type, tuple, tuple], type] = {}


def _cache_key(origin: type, bases: tuple, axes: dict) -> tuple:
    """Create hashable cache key from axes dict."""
    # Sort axes for consistent hashing
    axes_tuple = tuple(sorted(axes.items()))
    return (origin, bases, axes_tuple)


# =============================================================================
# AXES METACLASS
# =============================================================================

class AxesMeta(type):
    """
    Metaclass for types with arbitrary semantic axes.
    
    Stores axes in __axes__ and provides uniform introspection.
    """
    
    def __new__(mcs, name: str, bases: tuple, namespace: dict,
                __axes__: Optional[Dict[str, Any]] = None, **kwargs):
        """Create type with axes metadata."""
        # Handle any remaining kwargs as axes
        axes = __axes__ or {}
        axes.update(kwargs)
        
        # Create the class
        cls = super().__new__(mcs, name, bases, namespace)
        
        # Attach axes metadata
        cls.__axes__ = axes
        
        # Also attach individual axes as __<name>__ for convenience
        for axis_name, axis_value in axes.items():
            setattr(cls, f"__{axis_name}__", axis_value)
        
        return cls
    
    def __repr__(cls) -> str:
        if hasattr(cls, '__axes__') and cls.__axes__:
            axes_str = ', '.join(f"{k}={v!r}" for k, v in cls.__axes__.items())
            return f"<class '{cls.__name__}' axes=({axes_str})>"
        return super().__repr__()
    
    def __hash__(cls) -> int:
        """Hash includes axes for type identity."""
        if hasattr(cls, '__axes__') and cls.__axes__:
            axes_tuple = tuple(sorted(cls.__axes__.items()))
            return hash((cls.__name__, cls.__bases__, axes_tuple))
        return super().__hash__()


# =============================================================================
# FACTORY FUNCTION - Mimics extended type() signature
# =============================================================================

def axes_type(name: str, bases: tuple, namespace: dict, **axes) -> type:
    """
    Create a type with arbitrary axes - prototype for extended type().
    
    This mimics the proposed signature:
        type(name, bases, namespace, **axes)
    
    Args:
        name: Class name
        bases: Base classes tuple
        namespace: Class namespace dict
        **axes: Arbitrary axes (scope=, registry=, version=, etc.)
    
    Returns:
        New type with __axes__ containing all axis values
    
    Example:
        MyStep = axes_type("MyStep", (Step,), {"process": fn},
                          scope="/pipeline/step_0",
                          registry=step_registry)
        
        MyStep.__axes__["scope"]  # "/pipeline/step_0"
        MyStep.__scope__          # "/pipeline/step_0" (convenience)
    """
    return AxesMeta(name, bases, namespace, __axes__=axes)


# =============================================================================
# AXES BASE CLASS - Enables class statement syntax via __init_subclass__
# =============================================================================

class AxesBase:
    """
    Base class that enables `class Foo(AxesBase, axes={...})` syntax.

    This works TODAY via __init_subclass__ (PEP 487, Python 3.6+).
    No grammar changes required!

    Usage:
        class Step(AxesBase):
            pass

        class MyStep(Step, axes={"scope": "/pipeline/step_0"}):
            pass

        MyStep.__axes__  # {'scope': '/pipeline/step_0'}

    Inheritance:
        Axes are inherited and merged per-key using MRO order.
        Child axes override parent axes for the same key.
    """
    __axes__: MappingProxyType = MappingProxyType({})

    def __init_subclass__(cls, axes: Optional[Dict[str, Any]] = None, **kwargs):
        super().__init_subclass__(**kwargs)

        # Collect axes from parent classes (MRO order, first wins)
        parent_axes: Dict[str, Any] = {}
        for parent in cls.__mro__[1:]:
            if hasattr(parent, '__axes__'):
                for k, v in parent.__axes__.items():
                    if k not in parent_axes:
                        parent_axes[k] = v

        # Child axes override parent axes
        if axes:
            parent_axes.update(axes)

        # Store as immutable mapping
        cls.__axes__ = MappingProxyType(parent_axes)

        # Also attach individual axes as __<name>__ for convenience
        for axis_name, axis_value in parent_axes.items():
            setattr(cls, f"__{axis_name}__", axis_value)


# =============================================================================
# DECORATOR - For class statement syntax (alternative to AxesBase)
# =============================================================================

def with_axes(**axes):
    """
    Decorator to attach axes to a class definition.

    Alternative to inheriting from AxesBase. Use when you can't modify
    the base class.

    Usage:
        @with_axes(scope="/pipeline/step_0", registry=STEP_REGISTRY)
        class MyStep(Step):
            pass

        MyStep.__axes__  # {"scope": "/pipeline/step_0", "registry": ...}

    Note: Prefer `class MyStep(Step, axes={...})` syntax when Step
    inherits from AxesBase - it's cleaner and doesn't require a decorator.
    """
    def decorator(cls: type) -> type:
        # Recreate the class with AxesMeta
        return AxesMeta(
            cls.__name__,
            cls.__bases__,
            dict(cls.__dict__),
            __axes__=axes
        )
    return decorator


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def get_axes(cls: type) -> Dict[str, Any]:
    """Get all axes from a type."""
    return getattr(cls, '__axes__', {})


def get_axis(cls: type, name: str, default: Any = None) -> Any:
    """Get a specific axis value."""
    return get_axes(cls).get(name, default)


def has_axis(cls: type, name: str) -> bool:
    """Check if type has a specific axis."""
    return name in get_axes(cls)

