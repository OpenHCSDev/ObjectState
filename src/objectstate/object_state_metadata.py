"""Contracted metadata storage for ObjectState extensions.

ObjectState.metadata is intentionally outside normal dirty detection, but it is
inside time-travel snapshots. Extension-owned metadata therefore needs a
contract: namespaced keys must be registered before they can be written,
captured, or restored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping
import copy


@dataclass(frozen=True)
class ObjectStateMetadataContract:
    """Registered extension-owned ObjectState metadata key."""

    key: str
    owner: str
    description: str

    def __post_init__(self) -> None:
        if "." not in self.key:
            raise ValueError(
                f"ObjectState metadata extension key must be namespaced: {self.key!r}"
            )
        if not self.owner:
            raise ValueError(f"ObjectState metadata contract {self.key!r} needs an owner")
        if not self.description:
            raise ValueError(
                f"ObjectState metadata contract {self.key!r} needs a description"
            )


class ObjectStateMetadataContractRegistry:
    """Process-local registry for extension-owned ObjectState metadata."""

    _contracts: ClassVar[dict[str, ObjectStateMetadataContract]] = {}

    @classmethod
    def register(cls, contract: ObjectStateMetadataContract) -> ObjectStateMetadataContract:
        existing = cls._contracts.get(contract.key)
        if existing is not None and existing != contract:
            raise ValueError(
                f"ObjectState metadata key {contract.key!r} is already registered "
                f"to {existing.owner!r}"
            )
        cls._contracts[contract.key] = contract
        return contract

    @classmethod
    def contract_for(cls, key: str) -> ObjectStateMetadataContract:
        contract = cls._contracts.get(key)
        if contract is None:
            raise KeyError(
                f"ObjectState extension metadata key {key!r} is not registered. "
                "Register ObjectStateMetadataContract before writing namespaced metadata."
            )
        return contract

    @classmethod
    def validate_key(cls, key: str) -> None:
        if "." in key:
            cls.contract_for(key)

    @classmethod
    def validate_mapping(
        cls,
        *,
        scope_id: str | None,
        metadata: Mapping[str, Any],
        operation: str,
    ) -> None:
        for key in metadata:
            try:
                cls.validate_key(key)
            except KeyError as exc:
                scope = scope_id if scope_id is not None else "<root>"
                raise RuntimeError(
                    f"Cannot {operation} ObjectState metadata for {scope}: {exc}"
                ) from exc


class ObjectStateMetadataStore(dict):
    """Dict-compatible metadata store that enforces extension contracts."""

    def __init__(
        self,
        scope_id: str | None,
        initial: Mapping[str, Any] | None = None,
    ) -> None:
        self.scope_id = scope_id
        super().__init__()
        if initial:
            self.update(initial)

    def _validate_contracts(
        self,
        *,
        operation: str,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        ObjectStateMetadataContractRegistry.validate_mapping(
            scope_id=self.scope_id,
            metadata=self if metadata is None else metadata,
            operation=operation,
        )

    def __setitem__(self, key: str, value: Any) -> None:
        ObjectStateMetadataContractRegistry.validate_key(key)
        super().__setitem__(key, value)

    def update(self, other: Mapping[str, Any] | None = None, **kwargs: Any) -> None:
        if other:
            self._validate_contracts(operation="write", metadata=other)
        if kwargs:
            self._validate_contracts(operation="write", metadata=kwargs)
        super().update(other or {}, **kwargs)

    def setdefault(self, key: str, default: Any = None) -> Any:
        ObjectStateMetadataContractRegistry.validate_key(key)
        return super().setdefault(key, default)

    def copy_for_snapshot(self) -> dict[str, Any]:
        self._validate_contracts(operation="snapshot")
        return copy.deepcopy(dict(self))

    def __copy__(self) -> "ObjectStateMetadataStore":
        return ObjectStateMetadataStore(self.scope_id, dict(self))

    def __deepcopy__(self, memo: dict[int, Any]) -> "ObjectStateMetadataStore":
        copied = ObjectStateMetadataStore(self.scope_id)
        memo[id(self)] = copied
        copied.update(copy.deepcopy(dict(self), memo))
        return copied

    @classmethod
    def from_snapshot(
        cls,
        *,
        scope_id: str | None,
        metadata: Mapping[str, Any],
    ) -> "ObjectStateMetadataStore":
        ObjectStateMetadataContractRegistry.validate_mapping(
            scope_id=scope_id,
            metadata=metadata,
            operation="restore",
        )
        return cls(scope_id, copy.deepcopy(dict(metadata)))
