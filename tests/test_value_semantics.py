"""Shared semantic value comparison contracts."""

from objectstate import semantic_values_equal


class AmbiguousEquality:
    """Value whose comparison result cannot be reduced to one truth value."""

    def __eq__(self, other: object):
        del other
        return self

    def __bool__(self) -> bool:
        raise ValueError("ambiguous")


def test_semantic_values_equal_compares_nested_unhashable_declarations() -> None:
    assert semantic_values_equal(
        {"channel": ["A", {"threshold": 2}]},
        {"channel": ["A", {"threshold": 2}]},
    )
    assert not semantic_values_equal(
        {"channel": ["A", {"threshold": 2}]},
        {"channel": ["A", {"threshold": 3}]},
    )


def test_semantic_values_equal_treats_ambiguous_equality_as_changed() -> None:
    assert not semantic_values_equal(AmbiguousEquality(), AmbiguousEquality())
