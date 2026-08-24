"""Canonical declaration owner type used by ObjectState path metadata."""

from collections.abc import Callable
from typing import Any, TypeAlias

ParameterOwner: TypeAlias = type | Callable[..., Any]
"""Type or callable declaration that owns an extracted parameter."""
