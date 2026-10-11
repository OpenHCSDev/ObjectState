"""Hierarchical scope identifiers for registered ObjectStates."""

from __future__ import annotations

from typing import ClassVar


class ScopeKey(str):
    """A scope id: segments joined by ``SEPARATOR``; the empty key is the global scope.

    A scope contains itself and every scope whose segments extend its own; the
    global scope contains every scope. ``ScopeKey`` is a ``str``, so it is a
    dictionary key and serializes as its text.
    """

    __slots__ = ()

    SEPARATOR: ClassVar[str] = "::"

    def __new__(cls, value: str | None = "") -> ScopeKey:
        return super().__new__(cls, "" if value is None else value)

    @classmethod
    def of(cls, *parts: str) -> ScopeKey:
        """Join ``parts`` into one key; each part is a single segment."""

        for part in parts:
            if not part or cls.SEPARATOR in part:
                raise ValueError(f"Scope segment {part!r} is empty or contains {cls.SEPARATOR!r}.")
        return cls(cls.SEPARATOR.join(parts))

    @property
    def is_global(self) -> bool:
        return not self

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(self.split(self.SEPARATOR)) if self else ()

    @property
    def depth(self) -> int:
        """Number of segments; the global scope has depth 0."""

        return len(self.parts)

    @property
    def last(self) -> str:
        """The final segment; the empty string for the global scope."""

        return self.parts[-1] if self else ""

    @property
    def root(self) -> ScopeKey:
        """The first segment as a key; the global scope is its own root."""

        return ScopeKey(self.parts[0]) if self else self

    @property
    def parent(self) -> ScopeKey:
        """The key without its final segment; a root's parent is the global scope."""

        return ScopeKey(self.SEPARATOR.join(self.parts[:-1]))

    def child(self, segment: str) -> ScopeKey:
        """The key one segment below this one."""

        return ScopeKey.of(*self.parts, segment)

    def ancestors(self) -> tuple[ScopeKey, ...]:
        """The global scope, then each prefix of this key, ending with the key itself."""

        parts = self.parts
        return (ScopeKey(),) + tuple(
            ScopeKey(self.SEPARATOR.join(parts[: index + 1])) for index in range(len(parts))
        )

    def contains(self, other: str | None) -> bool:
        """Whether ``other`` is this scope or below it."""

        other_key = ScopeKey(other)
        if self.is_global or other_key == self:
            return True
        return other_key.startswith(self + self.SEPARATOR)

    def strictly_contains(self, other: str | None) -> bool:
        """Whether ``other`` is below this scope and not the scope itself."""

        return ScopeKey(other) != self and self.contains(other)
