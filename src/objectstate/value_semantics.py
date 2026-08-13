"""Shared value comparison semantics for declaration and state reconciliation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def semantic_values_equal(left: object, right: object) -> bool:
    """Compare nested values without requiring hashability or scalar equality."""

    if left is right:
        return True
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            semantic_values_equal(left[key], right[key]) for key in left
        )
    if (
        isinstance(left, Sequence)
        and isinstance(right, Sequence)
        and not isinstance(left, (str, bytes, bytearray))
        and not isinstance(right, (str, bytes, bytearray))
    ):
        return len(left) == len(right) and all(
            semantic_values_equal(left_value, right_value)
            for left_value, right_value in zip(left, right)
        )
    try:
        comparison = left == right
    except Exception:
        return False
    try:
        return bool(comparison)
    except (TypeError, ValueError):
        return False
