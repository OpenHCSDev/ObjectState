"""
Parametric Axes Prototype - Arbitrary semantic axes for type construction.

This module prototypes extending type() to support arbitrary axes beyond (B, S).
Proof-of-concept for PEP proposal: extending type() with axes= parameter.

In the real CPython implementation, this logic would be in type.__new__ itself,
and every class would have __axes__ by default (empty MappingProxyType).

This prototype uses AxesMeta as a stand-in for what type() would do natively.
Once any class uses metaclass=AxesMeta, all subclasses inherit it automatically.

Usage:
    from objectstate.parametric_axes import AxesMeta

    # One class in hierarchy uses metaclass=AxesMeta
    class Step(metaclass=AxesMeta):
        pass

    # All subclasses automatically get axes support (metaclass inherited)
    class MyStep(Step, axes={"scope": "/pipeline/step_0"}):
        pass

    MyStep.__axes__["scope"]  # "/pipeline/step_0"

    # Per-key MRO inheritance works automatically
    class ChildStep(MyStep, axes={"priority": 1}):
        pass

    ChildStep.__axes__["scope"]     # "/pipeline/step_0" (inherited)
    ChildStep.__axes__["priority"]  # 1 (defined here)
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
    Metaclass prototype for type() with axes support.

    In the real CPython implementation, this logic would be in type.__new__,
    and every class would have __axes__ = MappingProxyType({}) by default.

    This metaclass is the stand-in: once any class uses metaclass=AxesMeta,
    all subclasses inherit it automatically (standard metaclass inheritance).
    """

    def __new__(mcs, name: str, bases: tuple, namespace: dict,
                axes: Optional[Dict[str, Any]] = None, **kwargs):
        """Create type with axes metadata and per-key MRO inheritance."""
        # Create the class
        cls = super().__new__(mcs, name, bases, namespace)

        # Per-key MRO inheritance: collect from parents, first wins
        parent_axes: Dict[str, Any] = {}
        for parent in cls.__mro__[1:]:
            for k, v in getattr(parent, '__axes__', {}).items():
                if k not in parent_axes:
                    parent_axes[k] = v

        # Child axes override parent axes
        if axes:
            parent_axes.update(axes)

        # Store as immutable mapping
        cls.__axes__ = MappingProxyType(parent_axes)

        # Convenience attributes: __scope__, __registry__, etc.
        for axis_name, axis_value in parent_axes.items():
            setattr(cls, f"__{axis_name}__", axis_value)

        return cls

    def __repr__(cls) -> str:
        if cls.__axes__:
            axes_str = ', '.join(f"{k}={v!r}" for k, v in cls.__axes__.items())
            return f"<class '{cls.__name__}' axes=({axes_str})>"
        return super().__repr__()


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
    return AxesMeta(name, bases, namespace, axes=axes)


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

