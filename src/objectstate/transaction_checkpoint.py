"""Exact local rollback boundary for an ObjectState transaction participant."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from objectstate.object_state import ObjectState
from objectstate.object_state_metadata import ObjectStateMetadataStore


@dataclass(frozen=True, slots=True)
class ObjectStateTransactionCheckpoint:
    """Capture and restore one ObjectState without changing its edit semantics.

    This is intentionally distinct from the serializable time-travel snapshot:
    a local transaction checkpoint retains the exact saved object and delegate
    identities as well as live unsaved edits and ephemeral reconstruction
    caches.
    """

    object_instance: Any
    extraction_target: Any
    parameters: dict[str, Any]
    saved_parameters: dict[str, Any]
    live_resolved: dict[str, Any] | None
    saved_resolved: dict[str, Any]
    live_provenance: dict[str, Any]
    metadata: dict[str, Any]
    cached_object: Any
    cached_object_applied: bool
    invalid_fields: frozenset[str]
    raw_dirty: bool
    dirty_fields: frozenset[str]
    signature_diff_fields: frozenset[str]
    last_changed_field: str | None
    last_changed_concrete_paths: frozenset[str]
    last_changed_paths: frozenset[str]
    last_changed_values: dict[str, Any]
    last_changed_meta_keys: frozenset[str]
    last_changed_meta_values: dict[str, Any]

    @classmethod
    def capture(cls, state: ObjectState) -> "ObjectStateTransactionCheckpoint":
        """Capture the exact local state before a fallible transaction."""

        copied = cls._copy_mappings(
            state,
            {
                "parameters": state.parameters,
                "saved_parameters": state._saved_parameters,
                "live_resolved": state._live_resolved,
                "saved_resolved": state._saved_resolved,
                "live_provenance": state._live_provenance,
                "last_changed_values": state._last_changed_values,
                "last_changed_meta_values": state._last_changed_meta_values,
            },
        )
        return cls(
            object_instance=state.object_instance,
            extraction_target=state._extraction_target,
            parameters=copied["parameters"],
            saved_parameters=copied["saved_parameters"],
            live_resolved=copied["live_resolved"],
            saved_resolved=copied["saved_resolved"],
            live_provenance=copied["live_provenance"],
            metadata=state.copy_metadata_for_snapshot(),
            cached_object=state._cached_object,
            cached_object_applied=state._cached_object_applied,
            invalid_fields=frozenset(state._invalid_fields),
            raw_dirty=state._raw_dirty,
            dirty_fields=frozenset(state._dirty_fields),
            signature_diff_fields=frozenset(state._signature_diff_fields),
            last_changed_field=state._last_changed_field,
            last_changed_concrete_paths=frozenset(
                state._last_changed_concrete_paths
            ),
            last_changed_paths=frozenset(state._last_changed_paths),
            last_changed_values=copied["last_changed_values"],
            last_changed_meta_keys=frozenset(state._last_changed_meta_keys),
            last_changed_meta_values=copied["last_changed_meta_values"],
        )

    def restore(self, state: ObjectState) -> None:
        """Restore the captured state and then publish one coherent change."""

        changed_fields = self._changed_fields(state)
        copied = self._copy_mappings(
            state,
            {
                "parameters": self.parameters,
                "saved_parameters": self.saved_parameters,
                "live_resolved": self.live_resolved,
                "saved_resolved": self.saved_resolved,
                "live_provenance": self.live_provenance,
                "last_changed_values": self.last_changed_values,
                "last_changed_meta_values": self.last_changed_meta_values,
            },
        )

        state.object_instance = self.object_instance
        state._extraction_target = self.extraction_target
        if state._delegate_attr is not None:
            setattr(
                state.object_instance,
                state._delegate_attr,
                self.extraction_target,
            )
        state.parameters = copied["parameters"]
        state._saved_parameters = copied["saved_parameters"]
        state._live_resolved = copied["live_resolved"]
        state._saved_resolved = copied["saved_resolved"]
        state._live_provenance = copied["live_provenance"]
        state.metadata = ObjectStateMetadataStore.from_snapshot(
            scope_id=state.scope_id,
            metadata=self.metadata,
        )
        state._cached_object = self.cached_object
        state._cached_object_applied = self.cached_object_applied
        state._invalid_fields = set(self.invalid_fields)
        state._raw_dirty = self.raw_dirty
        state._dirty_fields = set(self.dirty_fields)
        state._signature_diff_fields = set(self.signature_diff_fields)
        state._last_changed_field = self.last_changed_field
        state._last_changed_concrete_paths = set(
            self.last_changed_concrete_paths
        )
        state._last_changed_paths = set(self.last_changed_paths)
        state._last_changed_values = copied["last_changed_values"]
        state._last_changed_meta_keys = set(self.last_changed_meta_keys)
        state._last_changed_meta_values = copied["last_changed_meta_values"]

        if changed_fields:
            state._notify_resolved_changed(
                changed_fields,
                context="transaction_checkpoint_restore",
            )
            state._notify_state_changed(changed_fields)

    def _changed_fields(self, state: ObjectState) -> set[str]:
        fields: set[str] = set()
        missing = object()
        for current, target in (
            (state.parameters, self.parameters),
            (state._saved_parameters, self.saved_parameters),
            (state._live_resolved or {}, self.live_resolved or {}),
            (state._saved_resolved, self.saved_resolved),
        ):
            fields.update(
                key
                for key in set(current) | set(target)
                if not self._values_equal(
                    current.get(key, missing),
                    target.get(key, missing),
                )
            )
        return state._most_specific_notification_fields(fields)

    @staticmethod
    def _values_equal(left: Any, right: Any) -> bool:
        """Compare checkpoint values without assuming scalar equality."""

        if left is right:
            return True
        try:
            comparison = left == right
        except Exception:
            return False
        try:
            return bool(comparison)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _copy_mappings(
        state: ObjectState,
        mappings: dict[str, Any],
    ) -> dict[str, Any]:
        memo: dict[int, Any] = {}
        seen: set[int] = set()
        state._seed_callable_identity_memo(mappings, memo, seen)
        return copy.deepcopy(mappings, memo)
