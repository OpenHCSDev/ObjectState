"""Shared plain-data comparison, copy identity and collection projection."""
from __future__ import annotations

from collections.abc import Mapping, Sequence


def semantic_values_equal(left: object, right: object) -> bool:
    if left is right:
        return True
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            semantic_values_equal(left[key], right[key]) for key in left
        )
    if (isinstance(left, Sequence) and isinstance(right, Sequence)
            and not isinstance(left, (str, bytes, bytearray))
            and not isinstance(right, (str, bytes, bytearray))):
        return len(left) == len(right) and all(
            semantic_values_equal(a, b) for a, b in zip(left, right)
        )
    return bool(left == right)


def seed_callable_identity(value, memo, seen):
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    if callable(value):
        memo[identity] = value
    elif isinstance(value, Mapping):
        for key, child in value.items():
            seed_callable_identity(key, memo, seen)
            seed_callable_identity(child, memo, seen)
    elif isinstance(value, (Sequence, set, frozenset)) and not isinstance(value, (str, bytes, bytearray)):
        for child in value:
            seed_callable_identity(child, memo, seen)
