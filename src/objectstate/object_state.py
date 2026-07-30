"""
ObjectState: Extracted MODEL from ParameterFormManager.

This class holds configuration state independently of UI widgets.
Lifecycle: Created when object added to pipeline, persists until removed.
PFM attaches to ObjectState when editor opens, detaches when closed.

FieldProxy: Type-safe proxy for accessing ObjectState fields via dotted attribute syntax.
"""
from dataclasses import is_dataclass, fields as dataclass_fields
import logging
from types import FunctionType
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, TypeAlias
import copy

from objectstate.object_state_metadata import (
    ObjectStateMetadataContract,
    ObjectStateMetadataContractRegistry,
    ObjectStateMetadataStore,
)
from objectstate.object_state_registry import ObjectStateRegistry
from objectstate.field_access import DataclassFieldAccess, DottedFieldPath
from objectstate.subfield_semantics import (
    MISSING,
    ObjectStateSubfieldSemanticIndex,
    build_subfield_semantic_index,
    changed_structural_leaf_paths,
)
from objectstate.time_travel_profile import TimeTravelProfiler

logger = logging.getLogger(__name__)

ParameterOwner: TypeAlias = type | Callable[..., Any]

class FieldProxy:
    """Type-safe proxy for accessing ObjectState fields via dotted attribute syntax.

    Provides IDE autocomplete while using flat internal storage:
    - External API: state.fields.well_filter_config.well_filter (type-safe)
    - Internal: state.parameters['well_filter_config.well_filter'] (flat dict)
    """

    def __init__(self, state: 'ObjectState', path: str, field_type: type):
        """Initialize FieldProxy.

        Args:
            state: The ObjectState this proxy accesses
            path: Current dotted path (empty for root)
            field_type: Type of the object at this path
        """
        object.__setattr__(self, '_state', state)
        object.__setattr__(self, '_path', path)
        object.__setattr__(self, '_type', field_type)

    def __getattr__(self, name: str) -> Any:
        """Get field value or nested FieldProxy.

        Args:
            name: Field name to access

        Returns:
            FieldProxy for nested dataclass fields, or resolved value for leaf fields
        """
        new_path = f'{self._path}.{name}' if self._path else name

        # Get field info from the type
        if not is_dataclass(self._type):
            type_name = getattr(self._type, '__name__', str(self._type))
            raise AttributeError(f"{type_name} is not a dataclass")

        field_info = None
        for f in dataclass_fields(self._type):
            if f.name == name:
                field_info = f
                break

        if field_info is None:
            type_name = getattr(self._type, '__name__', str(self._type))
            raise AttributeError(f"{type_name} has no field '{name}'")

        # Check if field is a nested dataclass
        field_type = field_info.type

        # Handle Optional[DataclassType]
        from typing import get_origin, get_args, Union
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            if len(args) == 2 and type(None) in args:
                inner_type = next(arg for arg in args if arg is not type(None))
                if is_dataclass(inner_type) and isinstance(inner_type, type):
                    return FieldProxy(self._state, new_path, inner_type)

        # Handle direct dataclass type
        if isinstance(field_type, type) and is_dataclass(field_type):
            return FieldProxy(self._state, new_path, field_type)

        # Leaf field - get resolved value
        return self._state.get_resolved_value(new_path)

    def __setattr__(self, name: str, value: Any) -> None:
        """Prevent attribute setting - use state.update_parameter() instead."""
        _ = (name, value)  # Suppress unused warnings
        raise AttributeError("FieldProxy is read-only. Use state.update_parameter(path, value) to set values.")


class ObjectState:
    """
    UI-independent state for editing and resolving one backing object.

    Lifecycle:
    - Created at the backing object's lifecycle boundary, before any editor.
    - Persists independently of windows that attach to it.
    - Unregistered when the backing object leaves its owning scope.

    State ownership:
    - ``parameters`` is the flat mutable working copy. Nested dataclass fields
      use dotted paths and do not create recursive ObjectState instances.
    - ``_saved_parameters`` and ``_saved_resolved`` are the explicit saved
      baseline; ``_live_resolved`` and ``_live_provenance`` describe the
      current resolved view.
    - ``_parent_state`` links independently scoped states for context and
      notification. It is not structural ownership of a nested dataclass.
    - ``scope_id`` is the registry identity.

    Dirty fields and signature differences are materialized from the raw and
    resolved snapshots. Structural leaf identities are read-only projections
    of the owning flat field, not additional writable state.
    """

    def __init__(
        self,
        object_instance: Any,
        scope_id: Optional[str] = None,
        parent_state: Optional['ObjectState'] = None,
        exclude_params: Optional[List[str]] = None,
        initial_values: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize ObjectState with minimal attributes.

        Args:
            object_instance: The object being edited (dataclass, callable, etc.)
                             If the object declares __objectstate_delegate__, parameters
                             are extracted from that attribute instead (delegation pattern).
            scope_id: Scope identifier for filtering (e.g., "/path::step_0")
            parent_state: Parent independently scoped ObjectState used for
                          context and parent notification.
            exclude_params: Parameters to exclude from extraction.
            initial_values: Initial values to override extracted defaults (e.g., saved kwargs)
        """
        # === Core State (3 attributes) ===
        self.object_instance = object_instance
        # Use passed scope_id if provided, otherwise inherit from parent
        # Editors may pass explicit scope_id values for nested parameter scopes.
        # Nested dataclass configs may omit scope_id and inherit from parent
        self.scope_id = scope_id if scope_id is not None else (parent_state.scope_id if parent_state else None)

        # === Delegation Support ===
        # Check if object declares a delegate for parameter extraction.
        # This allows storing a lifecycle object (e.g., orchestrator) while
        # extracting editable parameters from a nested config (e.g., pipeline_config).
        delegate_attr = getattr(type(object_instance), '__objectstate_delegate__', None)
        if delegate_attr:
            self._extraction_target = getattr(object_instance, delegate_attr)
            self._delegate_attr = delegate_attr
            logger.debug(f"ObjectState delegation: extracting from '{delegate_attr}' attribute")
        else:
            self._extraction_target = object_instance
            self._delegate_attr = None

        # === Flat Storage (NEW - for flattened architecture) ===
        self._path_to_type: Dict[str, ParameterOwner] = {}  # Maps dotted paths to their owner target
        self._direct_parameter_paths: dict[
            DottedFieldPath,
            tuple[DottedFieldPath, ...],
        ] = {}
        self._cached_object: Optional[Any] = None  # Cached result of to_object()
        self._cached_object_applied: bool = False  # True if cached delegate was applied to object_instance

        # UI / integration metadata (never participates in dirty detection).
        # Namespaced extension keys are contract-checked so time-travel cannot
        # silently snapshot or restore extension state it does not understand.
        self.metadata: ObjectStateMetadataStore = ObjectStateMetadataStore(self.scope_id)

        # Time-travel navigation helpers (set by ObjectStateRegistry time travel)
        # Maps param_name -> (before, after) for the last time-travel transition.
        self._last_changed_values: Dict[str, Tuple[Any, Any]] = {}

        # Maps metadata key -> (before, after) for the last time-travel transition.
        self._last_changed_meta_keys: Set[str] = set()
        self._last_changed_meta_values: Dict[str, Tuple[Any, Any]] = {}

        # Extract parameters using FLAT extraction (dotted paths)
        # This replaces the old UnifiedParameterAnalyzer + _create_nested_states() approach
        self.parameters: Dict[str, Any] = {}
        self._signature_defaults: Dict[str, Any] = {}
        # Maps dotted paths to their descriptions (value may be None when no description exists).
        self._parameter_descriptions: Dict[str, Optional[str]] = {}

        # Store excluded params and their original values for reconstruction
        # Excluded constructor parameters must be preserved for reconstruction.
        self._exclude_param_names: List[str] = list(exclude_params or [])  # For restore_saved()
        self._excluded_params: Dict[str, Any] = {}
        extraction_target = self._extraction_target
        for param_name in self._exclude_param_names:
            if hasattr(extraction_target, param_name):
                self._excluded_params[param_name] = getattr(extraction_target, param_name)

        # Flatten parameter extraction - walk nested dataclasses recursively.
        # Uses _extraction_target (delegate) instead of object_instance for
        # delegation support. The structure and its immutable path index are
        # replaced atomically once for this extraction.
        self._replace_parameter_structure(
            extraction_target,
            exclude_params=self._exclude_param_names,
            initial_values=initial_values,
        )

        # === Structure (1 attribute) ===
        self._parent_state: Optional['ObjectState'] = parent_state
        # NOTE: nested_states DELETED - flat storage eliminates nested ObjectState instances

        # === Cache (3 attributes) ===
        self._live_resolved: Optional[Dict[str, Any]] = None  # None = needs full compute
        self._invalid_fields: Set[str] = set()  # Fields needing partial recompute
        # Maps dotted_path → (source_scope_id, source_type) for inherited fields
        # source_type may differ from local container_type due to MRO inheritance
        self._live_provenance: Dict[str, Tuple[Optional[str], Optional[type]]] = {}

        # === Saved baseline (2 attributes) ===
        self._saved_resolved: Dict[str, Any] = {}
        self._saved_parameters: Dict[str, Any] = {}  # Immutable snapshot for diff on restore

        # === Materialized diffs (3 attributes) ===
        self._raw_dirty = False
        self._dirty_fields: Set[str] = set()
        self._signature_diff_fields: Set[str] = set()

        # === Change tracking for navigation (2 attributes) ===
        # Track which field most recently changed VALUE (not just dirty status)
        # Used for time-travel navigation to scroll to what changed in a transition
        self._last_changed_field: Optional[str] = None
        self._last_changed_concrete_paths: Set[str] = set()
        self._last_changed_paths: Set[str] = set()

        # === Flags (kept for batch operations) ===
        self._in_reset = False
        self._block_cross_window_updates = False
        self._forwarding_to_parent = False
        self._parent_field_name: Optional[str] = None

        # === State Change Callbacks ===
        # Callbacks notified when materialized state changes (dirty/signature diffs)
        self._on_state_changed_callbacks: List[Callable[[Set[str]], None]] = []

        # === Resolved Change Callbacks ===
        # Callbacks notified when resolved values actually change (for UI flashing)
        self._on_resolved_changed_callbacks: List[Callable[[Set[str]], None]] = []

        # === Time-Travel Callbacks ===
        # Callbacks notified when time-travel restores parameters (for widget refresh)
        self._on_time_travel_callbacks: List[Callable[[], None]] = []

        # === Time-Travel ===
        # Instance-level time-travel removed - use ObjectStateRegistry class-level DAG instead

        # Initialize baselines (suppress flash during init)
        self._ensure_live_resolved(notify_flash=False)
        assert self._live_resolved is not None  # Guaranteed by _ensure_live_resolved

        # CRITICAL: Initialize _saved_parameters BEFORE _compute_resolved_snapshot(use_saved=True)
        # because that method reads from _saved_parameters to get raw values.
        self._saved_parameters = self._copy_parameters_for_saved_baseline()

        # CRITICAL: Compute saved_resolved using SAVED ancestor context, not LIVE.
        # This ensures saved baseline represents "what would this object's values be
        # if all ancestors were at their saved state", NOT "what are values right now
        # with ancestor's unsaved edits baked in".
        #
        # If we used copy.deepcopy(_live_resolved), we'd bake in ancestor's unsaved
        # edits, causing inverted dirty state when ancestor is saved/reset.
        self._saved_resolved = self._compute_resolved_snapshot(use_saved=True)

        # DEBUG: Log live vs saved at registration
        logger.debug(f"🔵 INIT_RESOLVED: scope={self.scope_id!r} obj_type={type(self.object_instance).__name__}")
        for k in sorted(self._live_resolved.keys()):
            live_val = self._live_resolved.get(k)
            saved_val = self._saved_resolved.get(k)
            if live_val != saved_val:
                logger.debug(f"🔵 INIT_DIFF: {k!r} live={live_val!r} saved={saved_val!r}")

        # Materialize initial diff sets (no notification during init)
        # Should be empty for new objects since saved = live
        self._dirty_fields = self._compute_dirty_fields()
        self._signature_diff_fields = self._compute_signature_diff_fields()

        # NOTE: Don't record "init" snapshot here - each ObjectState would create a separate
        # snapshot missing other ObjectStates created later. Instead, the first edit will
        # record the baseline state automatically (see record_snapshot logic).

    def set_extension_metadata(
        self,
        contract: ObjectStateMetadataContract,
        value: Any,
    ) -> None:
        """Write extension metadata through a registered time-travel contract."""

        ObjectStateMetadataContractRegistry.register(contract)
        self.metadata[contract.key] = value

    def validate_metadata_contracts(self, operation: str) -> None:
        """Raise if ObjectState metadata contains unregistered extension keys."""

        ObjectStateMetadataContractRegistry.validate_mapping(
            scope_id=self.scope_id,
            metadata=self.metadata,
            operation=operation,
        )

    def copy_metadata_for_snapshot(self) -> Dict[str, Any]:
        """Return validated metadata payload for StateSnapshot."""

        return self.metadata.copy_for_snapshot()

    @property
    def context_obj(self) -> Optional[Any]:
        """Derive context_obj from parent_state (no separate attribute needed)."""
        return self._parent_state.object_instance if self._parent_state else None

    def _check_and_sync_delegate(self) -> bool:
        """Check if delegate attribute has changed and sync extraction target if needed.

        This implements auto-detection of delegate changes (Option 3 from architectural discussion).
        When object_instance's delegate attribute is replaced with a new instance (e.g., after
        rebuild_lazy_config_with_new_global_reference()), this method detects the change and
        automatically re-extracts parameters from the new delegate.

        Returns:
            True if delegate was detected as changed and re-extraction occurred, False otherwise.
        """
        if self._delegate_attr is None:
            # Not using delegation - nothing to check
            return False

        try:
            current_delegate = object.__getattribute__(self.object_instance, self._delegate_attr)
        except AttributeError:
            # Delegate attribute no longer exists - this is unexpected but handle gracefully
            logger.warning(
                f"Delegate attribute '{self._delegate_attr}' no longer exists on "
                f"{type(self.object_instance).__name__}. Keeping current extraction target."
            )
            return False

        # Use identity check (is) not equality (==) to detect if it's a new instance
        if current_delegate is self._extraction_target:
            # Delegate hasn't changed - no sync needed
            return False

        # Delegate has changed to a new instance - sync extraction target and re-extract
        logger.debug(
            f"Auto-detected delegate change for ObjectState(scope={self.scope_id!r}): "
            f"'{self._delegate_attr}' attribute was replaced with new instance. Re-extracting parameters."
        )

        self.update_object_instance(current_delegate)
        return True

    @property
    def has_delegate(self) -> bool:
        """Return whether this state extracts parameters through an object delegate."""

        return self._delegate_attr is not None

    def _copy_parameters_for_saved_baseline(self) -> Dict[str, Any]:
        """Snapshot raw parameters without cloning callable identity values.

        Callables can be semantic identities in object declarations. A plain
        deepcopy can rebuild callable wrapper instances through ``__reduce__``,
        making live and saved function specs unequal immediately after load.
        """
        memo: Dict[int, Any] = {}
        self._seed_callable_identity_memo(self.parameters, memo, set())
        return copy.deepcopy(self.parameters, memo)

    @classmethod
    def copy_parameter_pair_preserving_callable_identity(
        cls,
        parameters: Dict[str, Any],
        saved_parameters: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Copy live/saved raw parameters as one identity-preserving pair.

        Time-travel snapshots must preserve callable identity relationships across
        `parameters` and `_saved_parameters`. Copying the two dicts independently
        can rebuild callable wrappers twice and make a clean state appear dirty.
        """

        memo: Dict[int, Any] = {}
        seen: Set[int] = set()
        cls._seed_callable_identity_memo(parameters, memo, seen)
        cls._seed_callable_identity_memo(saved_parameters, memo, seen)
        return copy.deepcopy(parameters, memo), copy.deepcopy(saved_parameters, memo)

    @classmethod
    def _seed_callable_identity_memo(
        cls,
        value: Any,
        memo: Dict[int, Any],
        seen: Set[int],
    ) -> None:
        value_id = id(value)
        if value_id in seen:
            return
        seen.add(value_id)

        if callable(value):
            memo[value_id] = value
            return

        if isinstance(value, dict):
            for key, item in value.items():
                cls._seed_callable_identity_memo(key, memo, seen)
                cls._seed_callable_identity_memo(item, memo, seen)
            return

        if isinstance(value, (list, tuple, set, frozenset)):
            for item in value:
                cls._seed_callable_identity_memo(item, memo, seen)
            return

        if is_dataclass(value) and not isinstance(value, type):
            for field in dataclass_fields(value):
                cls._seed_callable_identity_memo(
                    object.__getattribute__(value, field.name),
                    memo,
                    seen,
                )

    @property
    def saved_object(self) -> Any:
        """Get the saved baseline object with the correct type.

        For delegation: returns _extraction_target (the delegate/config)
        For non-delegation: returns object_instance

        This is the object that should be used for context resolution when
        use_saved=True. It represents the "saved" state of the editable object.
        """
        # Auto-detect delegate changes before returning extraction target
        self._check_and_sync_delegate()
        return self._extraction_target

    @property
    def fields(self) -> FieldProxy:
        """Type-safe field access via FieldProxy.

        Returns:
            FieldProxy for accessing fields with IDE autocomplete:
            state.fields.well_filter_config.well_filter → resolved value
        """
        return FieldProxy(self, '', type(self.object_instance))

    def to_resolved_object(self) -> Any:
        """Reconstruct this state as an object with live resolved values."""
        self._check_and_sync_delegate()
        self._ensure_live_resolved()
        assert self._live_resolved is not None
        return self._reconstruct_from_resolved("", self._live_resolved)

    def to_saved_resolved_object(self) -> Any:
        """Reconstruct this state as an object with saved resolved values."""
        self._check_and_sync_delegate()
        if not self._saved_resolved:
            self._saved_resolved = self._compute_resolved_snapshot(use_saved=True)
        return self._reconstruct_from_resolved("", self._saved_resolved)

    @property
    def parameter_descriptions(self) -> Dict[str, Optional[str]]:
        """Get parameter descriptions for all parameters.

        Returns:
            Dictionary mapping dotted parameter paths to their descriptions (value may be None).
            E.g., {'well_filter_config.well_filter': 'Filter wells by...'}
        """
        return dict(self._parameter_descriptions)

    def type_for_path(self, field_path: str) -> ParameterOwner:
        """Return the ObjectState-recorded type for a dotted field path.

        Leaf paths return the dataclass/function owner that declares the
        field. Nested dataclass paths return the nested dataclass type itself.
        """
        if field_path == "":
            return type(self.object_instance)
        try:
            return self._path_to_type[field_path]
        except KeyError as exc:
            raise KeyError(
                f"ObjectState path is not registered: {field_path!r}"
            ) from exc

    def direct_parameter_paths(
        self,
        field_path: str = "",
    ) -> tuple[DottedFieldPath, ...]:
        """Return immutable direct-child paths for one flat parameter scope.

        The path topology is rebuilt when ObjectState extracts a replacement
        object. Values remain authoritative in ``parameters`` and are therefore
        never cached in this projection.
        """

        return self._direct_parameter_paths.get(DottedFieldPath(field_path), ())

    def has_parameter_descendants(self, field_path: str) -> bool:
        """Return whether an authoritative flat parameter owns child paths."""

        return bool(self.direct_parameter_paths(field_path))

    # === Resolved Change Subscription ===

    def on_resolved_changed(self, callback: Callable[[Set[str]], None]) -> None:
        """Subscribe to resolved value change notifications.

        The callback is called when resolved values actually change (not just when
        cache is invalidated). This enables UI components to flash/highlight
        specific fields when their resolved values change.

        Args:
            callback: Function that takes a Set[str] of changed dotted paths.
                      E.g., {'processing_config.group_by', 'well_filter_config.well_filter'}
        """
        if callback not in self._on_resolved_changed_callbacks:
            self._on_resolved_changed_callbacks.append(callback)

    def off_resolved_changed(self, callback: Callable[[Set[str]], None]) -> None:
        """Unsubscribe from resolved value change notifications."""
        if callback in self._on_resolved_changed_callbacks:
            self._on_resolved_changed_callbacks.remove(callback)

    def on_state_changed(self, callback: Callable[[Set[str]], None]) -> None:
        """Subscribe to materialized state change notifications (dirty/signature diffs)."""
        if callback not in self._on_state_changed_callbacks:
            self._on_state_changed_callbacks.append(callback)

    def off_state_changed(self, callback: Callable[[Set[str]], None]) -> None:
        """Unsubscribe from materialized state change notifications."""
        if callback in self._on_state_changed_callbacks:
            self._on_state_changed_callbacks.remove(callback)

    def _notify_state_changed(self, changed_paths: Set[str]) -> None:
        """Fire state change callbacks (best-effort)."""
        for callback in list(self._on_state_changed_callbacks):
            try:
                callback(changed_paths)
            except Exception as e:
                logger.warning(f"Error in state_changed callback: {e}")

    def _notify_resolved_changed(
        self,
        changed_paths: Set[str],
        *,
        context: str,
    ) -> None:
        """Publish resolved-value changes to registry and local subscribers."""
        if not changed_paths:
            return

        with TimeTravelProfiler.phase(
            "objectstate.notify_resolved_emit",
            scope=self.scope_id,
            context=context,
            changed_paths=len(changed_paths),
            callbacks=len(self._on_resolved_changed_callbacks),
        ):
            ObjectStateRegistry.notify_resolved_changed(self.scope_id, changed_paths)
        if not self._on_resolved_changed_callbacks:
            return

        logger.debug(
            "🔔 CALLBACK_LEAK_DEBUG: Notifying %d callbacks for scope=%s, "
            "context=%s, changed_paths=%s",
            len(self._on_resolved_changed_callbacks),
            self.scope_id,
            context,
            changed_paths,
        )
        for i, callback in enumerate(list(self._on_resolved_changed_callbacks)):
            try:
                with TimeTravelProfiler.phase(
                    "objectstate.notify_resolved_callback",
                    scope=self.scope_id,
                    context=context,
                    callback_index=i,
                    callback_count=len(self._on_resolved_changed_callbacks),
                    changed_paths=len(changed_paths),
                ):
                    callback(changed_paths)
            except RuntimeError as e:
                logger.warning(
                    "🔴 CALLBACK_LEAK_DEBUG: Dead callback #%d detected! "
                    "scope=%s, context=%s, error: %s",
                    i,
                    self.scope_id,
                    context,
                    e,
                )
            except Exception as e:
                logger.warning(
                    "Error in resolved_changed callback #%d during %s: %s",
                    i,
                    context,
                    e,
                )

    def forward_to_parent_state(self, field_path: Optional[str] = None) -> None:
        """Forward child state changes to parent state.

        Notifies the parent state that a field has conceptually changed, causing
        the parent's on_resolved_changed callbacks to fire (e.g., for UI flash).

        Args:
            field_path: Dotted path of the field that changed (e.g., 'config.value').
                       If None, uses _parent_field_name if set, otherwise defaults to scope suffix.

        Example:
            # In child ObjectState callback
            def on_child_changed(changed_paths):
                child_state.forward_to_parent_state('config.value')

        Raises:
            RuntimeError: If called on a state without a parent state.
        """
        if self._parent_state is None:
            raise RuntimeError(
                f"Cannot forward to parent: state '{self.scope_id}' has no parent state"
            )

        # Reentrancy guard (pattern from ObjectState architectural fixes)
        if self._forwarding_to_parent:
            logger.debug(f"[ObjectState] Reentrancy guard blocked for {self.scope_id}")
            return

        self._forwarding_to_parent = True
        try:
            # Determine which parent field changed
            # Priority: explicit field_path arg > _parent_field_name > auto-detect
            parent_field = field_path or self._parent_field_name
            if parent_field is None:
                # Auto-detect from a numeric scope suffix.
                parts = self.scope_id.split('::')
                if len(parts) >= 2:
                    last = parts[-1]
                    import re
                    m = re.match(r'^(.+?)_\d+$', last)
                    parent_field = m.group(1) if m else last

            if parent_field:
                self._parent_state._notify_resolved_changed(
                    {parent_field},
                    context="forward_to_parent_state",
                )
                
            logger.debug(
                "[ObjectState] Forwarded %s to parent, field=%r",
                self.scope_id,
                parent_field,
            )
            
        finally:
            self._forwarding_to_parent = False

    def _ensure_live_resolved(self, notify_flash: bool = True) -> Set[str]:
        """Ensure _live_resolved cache is populated.

        PERFORMANCE: Field-level invalidation only.
        - First access: full compute to populate cache
        - After update_parameter(): only recompute invalid fields
        - Cross-window access: return cached values directly (no work)

        Args:
            notify_flash: If True, fire on_resolved_changed callbacks for flash animations.
                          Set to False during initialization to suppress flash.

        Returns:
            Set of paths that changed (for flash). Empty if no changes.

        NOTE: This method handles CACHE + FLASH only. Caller handles _sync_materialized_state().
        """
        # First access - populate cache
        if self._live_resolved is None:
            self._live_resolved = self._compute_resolved_snapshot()
            self._invalid_fields.clear()
            return set()  # First populate - no "changes" to flash

        # Partial recompute for invalid fields only
        if self._invalid_fields:
            logger.debug(f"🔄 _ensure_live_resolved: scope={self.scope_id}, recomputing {len(self._invalid_fields)} invalid fields: {list(self._invalid_fields)}")
            changed_paths = self._recompute_invalid_fields()
            self._invalid_fields.clear()
        else:
            logger.debug(f"🔄 _ensure_live_resolved: scope={self.scope_id}, no invalid fields to recompute")
            changed_paths = set()

        if notify_flash and changed_paths:
            self._notify_resolved_changed(
                changed_paths,
                context="_ensure_live_resolved",
            )

        return changed_paths

    # DELETED: _create_nested_states() - No longer needed with flat storage
    # Nested ObjectStates are no longer created - flat storage handles all parameters

    def _analyze_parameters(self, obj: Any, exclude_params: Optional[List[str]] = None) -> Dict[str, Any]:
        """Analyze object parameters through the canonical introspection owner.

        Returns dict mapping param_name -> info object with .param_type, .default_value, and .description attributes.
        """
        from types import SimpleNamespace

        exclude_params = exclude_params or []
        result = {}

        # NOTE: python_introspect is a required dependency; fail loud if missing.
        # UnifiedParameterAnalyzer is responsible for correctness guarantees:
        # - defaults come from type/signature (never from instance)
        # - current instance values are accessed in a lazy-safe way (if needed)
        from python_introspect import UnifiedParameterAnalyzer

        ua_info = UnifiedParameterAnalyzer.analyze(obj, exclude_params=exclude_params)
        for name, info in ua_info.items():
            if name in exclude_params:
                continue
            result[name] = SimpleNamespace(
                param_type=getattr(info, "param_type", Any),
                default_value=getattr(info, "default_value", None),
                description=getattr(info, "description", None),
            )
        return result

    def _get_nested_dataclass_type(self, param_type: Any) -> Optional[type]:
        """Get the nested dataclass type if param_type is a nested dataclass.

        Args:
            param_type: The parameter type to check

        Returns:
            The dataclass type if nested, None otherwise
        """
        from typing import get_origin, get_args, Union

        # Check Optional[dataclass]
        origin = get_origin(param_type)
        if origin is Union:
            args = get_args(param_type)
            if len(args) == 2 and type(None) in args:
                inner_type = next(arg for arg in args if arg is not type(None))
                if is_dataclass(inner_type):
                    return inner_type

        # Check direct dataclass (but not the type itself)
        if is_dataclass(param_type) and not isinstance(param_type, type):
            # param_type is an instance, not a type - shouldn't happen but handle it
            return type(param_type)

        if is_dataclass(param_type):
            return param_type

        return None

    def reset_all_parameters(self) -> None:
        """Reset all parameters to defaults."""
        self._in_reset = True
        try:
            for param_name in list(self.parameters.keys()):
                self.reset_parameter(param_name)
        finally:
            self._in_reset = False

    def _dataclass_parameter_updates(self, prefix: str, value: Any) -> Dict[str, Any]:
        """Flatten a dataclass container update into registered child parameters."""
        if value is None or not is_dataclass(type(value)):
            return {}

        prefix_dot = f"{prefix}."
        if not any(
            path.startswith(prefix_dot)
            for path in self.parameters
            if path != prefix
        ):
            return {}

        updates: Dict[str, Any] = {}
        for field in dataclass_fields(value):
            field_path = f"{prefix_dot}{field.name}"
            field_value = DataclassFieldAccess.raw_value(value, field.name)
            if field_path in self.parameters:
                updates[field_path] = field_value
            updates.update(self._dataclass_parameter_updates(field_path, field_value))
        return updates

    def _dataclass_ancestor_parameter_updates(
        self,
        param_name: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Rebuild dataclass container parameters that own a changed child path."""

        if "." not in param_name:
            return {}

        updates: Dict[str, Any] = {}
        path_parts = param_name.split(".")
        for part_count in range(len(path_parts) - 1, 0, -1):
            prefix = ".".join(path_parts[:part_count])
            if prefix not in parameters:
                continue
            prefix_type = self._path_to_type.get(prefix)
            if not (isinstance(prefix_type, type) and is_dataclass(prefix_type)):
                continue

            rebuilt_value = self._reconstruct_from_parameter_snapshot(
                prefix,
                parameters,
            )
            if parameters.get(prefix) != rebuilt_value:
                updates[prefix] = rebuilt_value
                parameters[prefix] = rebuilt_value
        return updates

    def _is_flat_container_parameter(self, param_name: str, value: Any) -> bool:
        """Return whether a flat parameter entry represents a dataclass container."""

        if value is None or not is_dataclass(type(value)):
            return False
        prefix = f"{param_name}."
        return any(path.startswith(prefix) for path in self.parameters)

    def inheritance_field_paths(
        self,
        target_type: ParameterOwner,
        field_name: str,
    ) -> tuple[str, ...]:
        """Return flat field paths whose container type can inherit target_type."""

        from objectstate.lazy_factory import get_base_type_for_lazy

        if isinstance(target_type, type):
            target_base_type = get_base_type_for_lazy(target_type) or target_type
        else:
            target_base_type = target_type

        paths: list[str] = []
        for dotted_path, container_type in self._path_to_type.items():
            if dotted_path not in self.parameters:
                continue
            if not (dotted_path.endswith(f".{field_name}") or dotted_path == field_name):
                continue

            if isinstance(container_type, type):
                container_base_type = (
                    get_base_type_for_lazy(container_type) or container_type
                )
            else:
                container_base_type = container_type

            type_matches = container_base_type == target_base_type
            if (
                not type_matches
                and isinstance(container_base_type, type)
                and isinstance(target_base_type, type)
            ):
                type_matches = any(
                    (get_base_type_for_lazy(mro_class) or mro_class)
                    == target_base_type
                    for mro_class in container_base_type.__mro__
                )

            if type_matches:
                paths.append(dotted_path)

        return tuple(paths)

    def update_parameter(self, param_name: str, value: Any) -> Set[str]:
        """Update parameter value in state.

        Enforces invariants:
        1. State mutation → scope+type+field aware cache invalidation
        2. State mutation → global token increment (for live context cache)

        PERFORMANCE: Three-tier filtering for minimal invalidation:
        - SCOPE: Only descendants of this scope (they inherit from us)
        - TYPE: Only states with this type in their tree
        - FIELD: Only the specific field that changed

        Args:
            param_name: Name of parameter to update
            value: New value

        Returns:
            Resolved field paths whose visible values changed.
        """
        # Auto-detect delegate changes before parameter access
        self._check_and_sync_delegate()

        if param_name not in self.parameters:
            logger.warning(
                f"⚠️ update_parameter({param_name!r}) called on ObjectState(scope={self.scope_id!r}) "
                f"but parameter does not exist. Available: {list(self.parameters.keys())[:5]}..."
            )
            return set()

        child_updates = self._dataclass_parameter_updates(param_name, value)
        pending_parameters = dict(self.parameters)
        pending_parameters[param_name] = value
        for child_path, child_value in child_updates.items():
            pending_parameters[child_path] = child_value
        ancestor_updates = self._dataclass_ancestor_parameter_updates(
            param_name,
            pending_parameters,
        )

        # EARLY EXIT: No change, no invalidation, no flash
        current_value = self.parameters[param_name]
        changed_child_params = {
            child_path
            for child_path, child_value in child_updates.items()
            if self.parameters.get(child_path) != child_value
        }
        changed_ancestor_params = {
            ancestor_path
            for ancestor_path, ancestor_value in ancestor_updates.items()
            if self.parameters.get(ancestor_path) != ancestor_value
        }
        changed_storage_params = set(changed_child_params) | changed_ancestor_params
        if current_value != value:
            changed_storage_params.add(param_name)
        if not changed_storage_params:
            return set()

        changed_semantic_params = set(changed_child_params)
        if current_value != value and not changed_child_params:
            changed_semantic_params.add(param_name)

        changed_param_values = self._changed_parameter_values(
            changed_semantic_params,
            pending_parameters,
        )
        value_change_notification_fields = self.notification_fields_for_value_changes(
            changed_param_values,
        )

        ObjectStateRegistry.ensure_baseline_snapshot()

        # Update state directly (no type conversion - that's VIEW responsibility)
        self.parameters[param_name] = value
        for child_path, child_value in child_updates.items():
            self.parameters[child_path] = child_value
        for ancestor_path, ancestor_value in ancestor_updates.items():
            self.parameters[ancestor_path] = ancestor_value

        # SELF-INVALIDATION: Mark changed fields and same-state inherited siblings.
        local_invalidations = set(changed_semantic_params)
        # Descendants resolve through ancestor live values. Recompute this state
        # before cascading invalidation so child snapshots cannot lag one edit
        # behind their parent.
        changed_paths = self._ensure_live_resolved(notify_flash=False)

        for changed_param in changed_semantic_params:
            container_type = self._path_to_type.get(changed_param, type(self.object_instance))
            leaf_field_name = changed_param.split('.')[-1] if '.' in changed_param else changed_param
            local_invalidations.update(
                self.inheritance_field_paths(container_type, leaf_field_name)
            )
        self._invalid_fields.update(local_invalidations)
        self._cached_object = None  # Invalidate cached reconstructed object
        self._cached_object_applied = False

        # GLOBAL CONFIG EXCEPTION: Update LIVE thread-local FIRST, BEFORE invalidating descendants!
        # This is critical: descendants re-resolve during invalidation, so they need to see
        # the NEW value in the LIVE thread-local, not the old one.
        obj_type = type(self.object_instance)
        from objectstate.lazy_factory import is_global_config_type
        if is_global_config_type(obj_type):
            try:
                from objectstate.global_config import set_live_global_config, get_live_global_config
                from objectstate.context_manager import clear_current_temp_global
                from objectstate.lazy_factory import replace_raw

                # Get current LIVE config
                current_live = get_live_global_config(obj_type)
                if current_live is not None:
                    # Do a quick partial update to set the new value in LIVE thread-local
                    if '.' in param_name:
                        # Nested field like 'well_filter_config.well_filter'
                        parts = param_name.split('.')
                        nested_config_name = parts[0]
                        nested_field_name = '.'.join(parts[1:])

                        # Get nested config using object.__getattribute__ to avoid lazy resolution
                        try:
                            nested_config = object.__getattribute__(current_live, nested_config_name)
                        except AttributeError:
                            nested_config = None

                        if nested_config is not None and is_dataclass(nested_config):
                            # Update the nested config with the new value
                            updated_nested = replace_raw(nested_config, **{nested_field_name: value})
                            # Update LIVE thread-local with the updated nested config
                            temp_live = replace_raw(current_live, **{nested_config_name: updated_nested})
                            set_live_global_config(obj_type, temp_live)
                    else:
                        # Top-level field
                        temp_live = replace_raw(current_live, **{param_name: value})
                        set_live_global_config(obj_type, temp_live)

                # Clear cached context so resolution uses updated LIVE thread-local
                clear_current_temp_global()

                # DEBUG: Log well_filter value
                if 'well_filter' in param_name:
                    verify_live = get_live_global_config(obj_type)
                    try:
                        wf_value = object.__getattribute__(verify_live.well_filter_config, 'well_filter')
                        logger.debug(f"🔍 LIVE thread-local updated BEFORE invalidation: {obj_type.__name__}.{param_name} = {value}, well_filter={wf_value}")
                    except:
                        pass
            except Exception as e:
                logger.warning(f"Failed to update LIVE thread-local: {e}")

        for changed_param in changed_semantic_params:
            # SCOPE + TYPE + FIELD AWARE INVALIDATION:
            # Get the CONTAINER type for this field (e.g., WellFilterConfig for 'well_filter_config.well_filter')
            # This is critical for sibling inheritance: when WellFilterConfig.well_filter changes,
            # we need to invalidate PathPlanningConfig.well_filter (which inherits from WellFilterConfig)
            container_type = self._path_to_type.get(changed_param, type(self.object_instance))

            # Extract leaf field name for invalidation matching
            leaf_field_name = changed_param.split('.')[-1] if '.' in changed_param else changed_param

            # DEBUG: Log invalidation for well_filter
            if 'well_filter' in changed_param:
                logger.debug(f"🔍 Invalidating descendants: scope={self.scope_id}, type={container_type.__name__}, field={leaf_field_name}")

            ObjectStateRegistry.invalidate_by_type_and_scope(
                scope_id=self.scope_id,
                changed_type=container_type,
                field_name=leaf_field_name
            )

        # Increment global token for LiveContextService.collect() cache invalidation
        ObjectStateRegistry.increment_token(notify=False)

        # Recompute live cache, then notify once from the materialized sync layer.
        # First-populate states have no prior resolved cache to diff against, so
        # raw changed child paths are the notification/navigation authority for
        # inline dataclass editors.
        self._set_last_changed_values(changed_param_values)
        # Sync materialized state (single point for dirty/sig_diff update + notification)
        self._sync_materialized_state(
            changed_value_fields=changed_paths | value_change_notification_fields
        )

        # Record snapshot for time-travel (registry-level for coherent system history)
        # Leaf edits record directly. Dataclass-container edits record when they
        # materialize changed flat child fields; those child paths are the UI and
        # time-travel navigation authority for inline editors.
        # A field is a container if there are other params that start with "param_name."
        param_path = DottedFieldPath(param_name)
        is_container = any(
            p != param_name and param_path.contains_path(p)
            for p in self.parameters.keys()
        )
        snapshot_field = (
            self._select_changed_field(changed_semantic_params)
            if is_container and changed_semantic_params
            else param_name
        )
        if snapshot_field:
            ObjectStateRegistry.record_snapshot(f"edit {snapshot_field}", self.scope_id)

        return changed_paths | value_change_notification_fields

    def get_resolved_value(self, param_name: str) -> Any:
        """Get resolved value for a field from the bulk snapshot.

        Args:
            param_name: Field name to resolve (can be dotted path like 'path_planning_config.well_filter')

        Returns:
            Resolved value from _live_resolved snapshot.
            For dataclass container fields, returns a reconstructed dataclass instance
            with all sub-fields populated from live resolved values.
        """
        # Auto-detect delegate changes before resolving values
        self._check_and_sync_delegate()
        self._ensure_live_resolved()
        assert self._live_resolved is not None  # Guaranteed by _ensure_live_resolved

        # Check if this is a container/dataclass field (has subfields in _live_resolved)
        prefix = f"{param_name}."
        has_subfields = any(key.startswith(prefix) for key in self._live_resolved.keys())

        if has_subfields:
            # This is a container field - reconstruct's dataclass from live resolved values
            field_type = self._path_to_type.get(param_name)
            if field_type is not None and is_dataclass(field_type):
                return self._reconstruct_from_resolved(param_name, self._live_resolved)

        result = self._live_resolved.get(param_name)

        # DEBUG: Log well_filter resolution
        if 'well_filter' in param_name:
            logger.debug(f"🔍 get_resolved_value: scope={self.scope_id!r}, obj_type={type(self.object_instance).__name__}, param={param_name}, value={result}")

        return result

    def get_saved_resolved_value(self, param_name: str) -> Any:
        """Get saved resolved value for a field from the saved snapshot.

        Unlike get_resolved_value() which returns live values (including unsaved edits),
        this returns the saved baseline with inheritance applied. This is useful for
        compilation and other operations that should only consider saved state.

        For container fields (dataclasses), this reconstructs the entire nested
        dataclass with all sub-fields populated from saved resolved values.

        Args:
            param_name: Field name to resolve (can be dotted path like 'path_planning_config.well_filter')

        Returns:
            Saved resolved value from _saved_resolved snapshot.
            For dataclass fields, returns a reconstructed dataclass instance.
        """
        # Auto-detect delegate changes before resolving values
        self._check_and_sync_delegate()

        # Ensure saved resolved cache is populated
        if not self._saved_resolved:
            self._saved_resolved = self._compute_resolved_snapshot(use_saved=True)

        # Check if this is a container/dataclass field (has subfields in _saved_resolved)
        prefix = f"{param_name}."
        has_subfields = any(key.startswith(prefix) for key in self._saved_resolved.keys())

        if has_subfields:
            # This is a container field - reconstruct's dataclass from saved resolved values
            field_type = self._path_to_type.get(param_name)
            if field_type is not None and is_dataclass(field_type):
                return self._reconstruct_from_resolved(param_name, self._saved_resolved)

        # Return the simple value (or None if not found)
        return self._saved_resolved.get(param_name)

    def subfield_semantics(
        self,
        owner_field_path: DottedFieldPath,
    ) -> ObjectStateSubfieldSemanticIndex:
        """Project dirty/default/inherited semantics for structural leaves.

        The owner field remains the only writable ObjectState field. Returned
        leaves are visual/projection identities under that owner, such as
        ``source_filters[0].match_type`` for a tuple of dataclass rows.
        """

        self._check_and_sync_delegate()
        self._ensure_live_resolved()
        assert self._live_resolved is not None
        if not self._saved_resolved:
            self._saved_resolved = self._compute_resolved_snapshot(use_saved=True)

        path = owner_field_path
        raw_value = self.parameters.get(path.value, MISSING)
        resolved_value = self.get_resolved_value(path.value)
        saved_resolved_value = self.get_saved_resolved_value(path.value)
        signature_default_value = self._signature_defaults.get(path.value, MISSING)

        return build_subfield_semantic_index(
            owner_field_path=path,
            raw_value=raw_value,
            resolved_value=resolved_value,
            saved_resolved_value=saved_resolved_value,
            signature_default_value=signature_default_value,
            owner_dirty=path.contains_any(self.dirty_fields),
            owner_signature_diff=path.contains_any(self.signature_diff_fields),
        )

    def _reconstruct_from_live_resolved(self, prefix: str) -> Any:
        """Recursively reconstruct dataclass from live resolved values.

        Similar to _reconstruct_from_saved_resolved but uses _live_resolved instead.
        Used by get_resolved_value() when requesting a container/dataclass field.

        Args:
            prefix: Current path prefix (e.g., 'napari_streaming_config')

        Returns:
            Reconstructed dataclass instance with resolved values from _live_resolved
        """
        from objectstate.lazy_factory import get_base_type_for_lazy

        # Determine the type to reconstruct
        if not prefix:
            obj_type = type(self._extraction_target)
        else:
            obj_type = self._path_to_type.get(prefix)
            if obj_type is None:
                raise ValueError(f"No type mapping for prefix: {prefix}")

        # Normalize to base type for lazy dataclasses
        obj_type = get_base_type_for_lazy(obj_type) or obj_type

        prefix_dot = f'{prefix}.' if prefix else ''

        # Collect direct fields and nested prefixes from live resolved values
        direct_fields = {}
        nested_prefixes = set()

        for path, value in self._live_resolved.items():
            if not path.startswith(prefix_dot):
                continue

            remainder = path[len(prefix_dot):]

            if '.' in remainder:
                # This is a nested field - collect the first component
                first_component = remainder.split('.')[0]
                nested_prefixes.add(first_component)
            else:
                # Direct field of this object
                direct_fields[remainder] = value

        # Reconstruct nested dataclasses first
        for nested_name in nested_prefixes:
            nested_path = f'{prefix_dot}{nested_name}'
            nested_obj = self._reconstruct_from_live_resolved(nested_path)
            direct_fields[nested_name] = nested_obj

        # Instantiate the dataclass with all resolved fields
        result = obj_type(**direct_fields)

        return result

    def _reconstruct_from_resolved(self, prefix: str, resolved_snapshot: Dict[str, Any]) -> Any:
        """Recursively reconstruct dataclass from resolved snapshot.

        Unified method for both live and saved resolved values. The only difference
        is which snapshot dict is passed in (_live_resolved or _saved_resolved).

        Args:
            prefix: Current path prefix (e.g., 'analysis_consolidation_config')
            resolved_snapshot: The snapshot dict to reconstruct from (_live_resolved or _saved_resolved)

        Returns:
            Reconstructed dataclass instance with resolved values
        """
        from objectstate.lazy_factory import get_base_type_for_lazy

        # Determine the type to reconstruct
        if not prefix:
            obj_type = type(self._extraction_target)
        else:
            obj_type = self._path_to_type.get(prefix)
            if obj_type is None:
                raise ValueError(f"No type mapping for prefix: {prefix}")

        # Normalize to base type for lazy dataclasses
        obj_type = get_base_type_for_lazy(obj_type) or obj_type

        prefix_dot = f'{prefix}.' if prefix else ''

        # Collect direct fields and nested prefixes from resolved snapshot
        direct_fields = {}
        nested_prefixes = set()

        for path, value in resolved_snapshot.items():
            if not path.startswith(prefix_dot):
                continue

            remainder = path[len(prefix_dot):]

            if '.' in remainder:
                # This is a nested field - collect the first component
                first_component = remainder.split('.')[0]
                nested_prefixes.add(first_component)
            else:
                # Direct field of this object
                direct_fields[remainder] = value

        # Reconstruct nested dataclasses first
        for nested_name in nested_prefixes:
            nested_path = f'{prefix_dot}{nested_name}'
            nested_obj = self._reconstruct_from_resolved(nested_path, resolved_snapshot)
            direct_fields[nested_name] = nested_obj

        # Instantiate the dataclass with all resolved fields
        result = obj_type(**direct_fields)

        return result

    def get_provenance(self, param_name: str) -> Optional[Tuple[str, type]]:
        """Get the source scope_id and type for an inherited field value.

        For fields where the local value is None (inherited), returns the scope_id
        of the ancestor that provided the value AND the type that has it.
        Used for click-to-source navigation in the UI.

        The source_type may differ from the local container type due to MRO inheritance.
        For example, WellFilterConfig.well_filter might inherit from PathPlanningConfig.

        NOTE: Returns provenance even when the resolved value is None (signature default).
        A "concrete None" just means the class default is None and nothing overrode it.

        Args:
            param_name: Field name (can be dotted path like 'path_planning_config.well_filter')

        Returns:
            (source_scope_id, source_type): The scope and type that provided the value,
            or None if the value is local (not inherited).
        """
        self._ensure_live_resolved()
        result = self._live_provenance.get(param_name)
        if result is None:
            return None  # Field is local, not inherited
        scope_id, source_type = result
        if scope_id is None or source_type is None:
            return None  # Field not found in hierarchy (shouldn't happen)
        return (scope_id, source_type)

    def find_path_for_type(self, container_type: type) -> Optional[str]:
        """Find the path prefix for a container type in this ObjectState.

        With flat storage, nested configs are identified by their path prefix.
        Given a container type (e.g., PathPlanningConfig), returns the path prefix
        (e.g., 'path_planning_config').

        Handles type normalization: LazyPathPlanningConfig matches PathPlanningConfig.

        Args:
            container_type: The type to find the path for

        Returns:
            Path prefix for the type, or None if not found.
            Returns "" (empty string) if type is the root object type.
        """
        from objectstate.lazy_factory import get_base_type_for_lazy

        # Normalize the container_type for comparison
        container_base = get_base_type_for_lazy(container_type) or container_type

        # Check if container_type matches the root object type
        root_type = type(self.object_instance)
        root_base = get_base_type_for_lazy(root_type) or root_type
        if container_base == root_base:
            return ""  # Root type has no prefix

        # Look for paths where the TYPE matches (normalized comparison)
        # The path for a nested config is the one WITHOUT a dot suffix that has the type
        for path, typ in self._path_to_type.items():
            typ_base = get_base_type_for_lazy(typ) or typ
            if not isinstance(typ_base, type):
                continue
            if typ_base == container_base and '.' not in path:
                return path

        return None

    def project_ui_visible_field_path(self, container_type: type, field_name: str) -> Optional[str]:
        """Project a container type and field name to the visible UI field path.

        Hidden configuration classes can own inherited values even when the form
        renders a visible subclass. ObjectState owns the path/type index, so this
        method is the authority for remapping hidden source types to a visible
        field path.
        """
        from objectstate.lazy_factory import get_base_type_for_lazy
        from objectstate.ui_visibility import UIVisibilityRegistry

        container_base = get_base_type_for_lazy(container_type) or container_type
        if UIVisibilityRegistry.is_hidden(container_base):
            return self._find_visible_subclass_field_path(container_base, field_name)

        path_prefix = self.find_path_for_type(container_type)
        if path_prefix is None:
            return None

        field_path = f"{path_prefix}.{field_name}" if path_prefix else field_name
        if field_path not in self._path_to_type and field_path not in self.parameters:
            return None
        return field_path

    def _find_visible_subclass_field_path(self, hidden_type: type, field_name: str) -> Optional[str]:
        """Find a rendered field path for a hidden config type via a visible subclass."""
        from objectstate.lazy_factory import get_base_type_for_lazy
        from objectstate.ui_visibility import UIVisibilityRegistry

        hidden_base = get_base_type_for_lazy(hidden_type) or hidden_type
        for path, typ in self._path_to_type.items():
            if "." in path:
                continue

            typ_base = get_base_type_for_lazy(typ) or typ
            if not isinstance(typ_base, type):
                continue
            if UIVisibilityRegistry.is_hidden(typ_base):
                continue
            if hidden_base not in typ_base.__mro__:
                continue

            field_path = f"{path}.{field_name}"
            if field_path in self._path_to_type or field_path in self.parameters:
                return field_path

        return None

    def resolve_for_type(self, container_type: type, field_name: str) -> Any:
        """Resolve a field value given the container type and field name.

        Convenience method for callers who have a config object but don't know
        its path in the flat storage. Finds the path prefix for the container type
        and constructs the full dotted path.

        Args:
            container_type: Type of the containing config (e.g., PathPlanningConfig)
            field_name: Field name within that config (e.g., 'well_filter')

        Returns:
            Resolved value, or None if not found
        """
        path_prefix = self.find_path_for_type(container_type)
        if path_prefix is None:
            # Type not found - try the field_name directly (top-level field)
            return self.get_resolved_value(field_name)

        full_path = f'{path_prefix}.{field_name}'
        return self.get_resolved_value(full_path)

    def invalidate_cache(self) -> None:
        """Invalidate resolved cache - forces full recompute on next access."""
        self._live_resolved = None
        self._live_provenance = {}  # Provenance must be recomputed with resolved values
        self._cached_object = None  # Also invalidate cached object

    def invalidate_self_and_nested(self) -> None:
        """Invalidate this state's cache.

        With flat storage, no nested states to invalidate.
        """
        self._live_resolved = None
        self._live_provenance = {}  # Provenance must be recomputed with resolved values
        self._invalid_fields.clear()  # Full invalidation, not field-level
        self._cached_object = None

    def invalidate_field(self, field_name: str) -> None:
        """Mark a specific field as needing recomputation.

        PERFORMANCE: Field-level invalidation - only the changed field
        needs recomputation, not all 20+ fields in the config.
        """
        if field_name in self.parameters:
            self._invalid_fields.add(field_name)

    @staticmethod
    def _select_changed_field(changed_paths: Set[str]) -> Optional[str]:
        """Choose a stable representative changed path for navigation."""
        if not changed_paths:
            return None
        return sorted(changed_paths, key=lambda path: (-path.count("."), path))[0]

    def _set_last_changed_values(
        self,
        changed_values: Dict[str, Tuple[Any, Any]],
    ) -> None:
        """Store the latest value changes for UI/time-travel navigation."""
        if not changed_values:
            return
        self._last_changed_concrete_paths = set(changed_values)
        self._last_changed_paths = self.notification_fields_for_value_changes(
            changed_values
        )
        self._last_changed_values = copy.deepcopy(changed_values)
        self._last_changed_field = self._select_changed_field(
            self._last_changed_paths
        )

    def _changed_parameter_values(
        self,
        changed_params: Set[str],
        pending_parameters: Dict[str, Any],
    ) -> Dict[str, Tuple[Any, Any]]:
        """Return old/new values for changed flat parameter paths."""

        changed_values: Dict[str, Tuple[Any, Any]] = {}
        for param_path in pending_parameters:
            if param_path not in changed_params:
                continue
            old_value = self.parameters.get(param_path)
            new_value = pending_parameters.get(param_path)
            if old_value != new_value:
                changed_values[param_path] = (old_value, new_value)
        return changed_values

    def notification_fields_for_value_changes(
        self,
        changed_values: Dict[str, Tuple[Any, Any]],
    ) -> Set[str]:
        """Return ObjectState display paths affected by concrete value changes."""

        fields: Set[str] = set()
        for param_path, (old_value, new_value) in changed_values.items():
            if self._is_flat_container_parameter(param_path, new_value):
                continue
            fields.add(param_path)
            fields.update(
                changed_structural_leaf_paths(
                    owner_field_path=DottedFieldPath(param_path),
                    old_value=old_value,
                    new_value=new_value,
                )
            )
        return fields

    @staticmethod
    def _most_specific_notification_fields(fields: Set[str]) -> Set[str]:
        """Drop container notifications when a concrete descendant path is present."""

        if len(fields) < 2:
            return set(fields)

        paths = tuple(DottedFieldPath(field) for field in fields)
        result: Set[str] = set()
        for field_path in paths:
            if any(
                field_path.value != candidate.value
                and field_path.contains_path(candidate)
                for candidate in paths
            ):
                continue
            result.add(field_path.value)
        return result

    def update_object_instance(self, new_instance: Any) -> None:
        """Replace object_instance with a new instance and re-extract parameters.

        This is used when the object being edited is replaced externally (e.g., from
        code mode execution). The ObjectState is updated to point to the new instance
        and parameters are re-extracted to match the new object's state.

        For delegation cases, this updates _extraction_target. For non-delegation cases,
        it updates object_instance directly.

        Args:
            new_instance: The new object instance to extract parameters from
        """
        self._ensure_live_resolved(notify_flash=False)
        old_live_resolved = copy.deepcopy(self._live_resolved or {})

        if self._delegate_attr is not None:
            # Delegation case: verify the new_instance matches the delegate type
            if type(new_instance) != type(self._extraction_target):
                logger.warning(
                    f"Type mismatch in update_object_instance for delegated ObjectState: "
                    f"expected {type(self._extraction_target).__name__}, got {type(new_instance).__name__}"
                )
            self._extraction_target = new_instance
            setattr(self.object_instance, self._delegate_attr, new_instance)
        else:
            # Non-delegation case: update object_instance directly
            self.object_instance = new_instance
            self._extraction_target = new_instance

        # Re-extract parameters from new instance
        self._replace_parameter_structure(
            new_instance,
            exclude_params=self._exclude_param_names
        )

        # Update saved parameters to match
        self._saved_parameters = self._copy_parameters_for_saved_baseline()

        self._cached_object = None
        self._cached_object_applied = False
        self._invalid_fields.clear()

        obj_type = type(self._extraction_target)
        from objectstate.lazy_factory import is_global_config_type
        if is_global_config_type(obj_type):
            from objectstate.context_manager import clear_current_temp_global
            from objectstate.global_config import set_global_config_for_editing

            set_global_config_for_editing(obj_type, self._extraction_target)
            clear_current_temp_global()

        self._live_resolved = self._compute_resolved_snapshot(use_saved=False)
        self._saved_resolved = self._compute_resolved_snapshot(use_saved=True)

        missing = object()
        changed_paths = {
            path
            for path in set(old_live_resolved) | set(self._live_resolved)
            if old_live_resolved.get(path, missing)
            != self._live_resolved.get(path, missing)
        }
        changed_values = {
            path: (
                old_live_resolved.get(path),
                self._live_resolved.get(path),
            )
            for path in changed_paths
        }

        self._set_last_changed_values(changed_values)

        self._notify_resolved_changed(
            self.notification_fields_for_value_changes(changed_values),
            context="update_object_instance",
        )

        self._sync_materialized_state()

        for path in changed_paths:
            container_type = self._path_to_type.get(path, type(self.object_instance))
            leaf_field_name = path.split(".")[-1]
            ObjectStateRegistry.invalidate_by_type_and_scope(
                scope_id=self.scope_id,
                changed_type=container_type,
                field_name=leaf_field_name,
                invalidate_saved=True,
            )

        self._set_last_changed_values(changed_values)

        if changed_paths:
            ObjectStateRegistry.increment_token(notify=True)

        logger.debug(
            f"Updated ObjectState(scope={self.scope_id!r}) to new instance of type {type(new_instance).__name__}"
        )

    def _recompute_invalid_fields(self) -> Set[str]:
        """Recompute only the invalid fields, not the entire snapshot.

        PERFORMANCE: For explicitly set values, use parameters directly.
        Only build context stack for inherited (None) values.

        Returns:
            Set of paths whose resolved values actually changed (for UI notification).
        """
        from objectstate.context_manager import build_context_stack

        changed_paths: Set[str] = set()
        changed_values: Dict[str, Tuple[Any, Any]] = {}

        # _live_resolved must exist when this is called (from _ensure_live_resolved)
        if self._live_resolved is None:
            return changed_paths

        # Separate explicit vs inherited fields, skipping container entries
        explicit_fields = []
        inherited_fields = []
        for name in self._invalid_fields:
            if name not in self.parameters:
                continue
            # Safety check: skip any container entries that might have leaked in
            # (containers should NOT be in parameters — only leaf fields are tracked)
            raw_value = self.parameters[name]
            if self._is_flat_container_parameter(name, raw_value):
                continue
            if raw_value is not None:
                explicit_fields.append(name)
            else:
                inherited_fields.append(name)

        # Explicit values: use parameters directly (no resolution needed)
        for name in explicit_fields:
            old_val = self._live_resolved.get(name)
            explicit_val = self.parameters[name]
            if old_val != explicit_val:
                changed_paths.add(name)
                changed_values[name] = (old_val, explicit_val)
                logger.debug(
                    f"RECOMPUTE EXPLICIT CHANGED [{self.scope_id}] {name}: "
                    f"old={old_val!r} -> new={explicit_val!r}"
                )
            self._live_resolved[name] = explicit_val
            # Clear provenance for explicit values - they're no longer inherited
            if name in self._live_provenance:
                del self._live_provenance[name]

        # Inherited values: need context stack for lazy resolution + provenance
        if inherited_fields:
            from objectstate.dual_axis_resolver import resolve_with_provenance
            from objectstate.lazy_factory import has_lazy_resolution

            # Get ancestor objects for context stack building
            # CRITICAL: Skip delegate sync to avoid re-entrant invalidate_cache() calls
            # that would destroy _live_resolved while we're computing it.
            ancestor_objects_with_scopes = ObjectStateRegistry.get_ancestor_objects_with_scopes(
                self.scope_id,
                skip_delegate_sync=True
            )

            # ARCHITECTURAL FIX: Reconstruct current object from parameters for real-time MRO.
            # Using object_instance (original saved state) gives stale values, breaking inheritance.
            # Calling to_object() with sync_delegate=False reconstructs from CURRENT parameters
            # without triggering delegate sync that would invalidate our cache mid-computation.
            current_obj = self.to_object(update_delegate=False, sync_delegate=False)

            stack = build_context_stack(
                object_instance=current_obj,
                ancestor_objects_with_scopes=ancestor_objects_with_scopes,
                current_scope_id=self.scope_id,
            )

            with stack:
                # For each inherited field, resolve using dual-axis resolution with provenance
                for dotted_path in inherited_fields:
                    container_type = self._path_to_type.get(dotted_path)
                    if container_type is None:
                        logger.debug(f"⚠️ _recompute: {dotted_path} has no container_type in _path_to_type")
                        continue
                    # Non-lazy fields with None stay as None rather than
                    # participating in contextual inheritance.
                    if not is_dataclass(container_type) or not has_lazy_resolution(container_type):
                        # Non-lazy field: just use raw value (None)
                        logger.debug(f"⚠️ _recompute: {dotted_path} has non-lazy container_type={container_type.__name__}, using raw value=None")
                        old_val = self._live_resolved.get(dotted_path)
                        raw_val = self.parameters.get(dotted_path)
                        if old_val != raw_val:
                            changed_paths.add(dotted_path)
                            changed_values[dotted_path] = (old_val, raw_val)
                        self._live_resolved[dotted_path] = raw_val
                        continue
                    parts = dotted_path.split('.')
                    field_name = parts[-1]

                    # Use resolve_with_provenance for SINGLE walk that gets both value AND source
                    value, source_scope_id, source_type = resolve_with_provenance(container_type, field_name)

                    old_val = self._live_resolved.get(dotted_path)
                    if old_val != value:
                        changed_paths.add(dotted_path)
                        changed_values[dotted_path] = (old_val, value)
                        logger.debug(
                            f"RECOMPUTE INHERITED CHANGED [{self.scope_id}] {dotted_path}: "
                            f"old={old_val!r} -> new={value!r}"
                        )
                    else:
                        logger.debug(
                            f"RECOMPUTE INHERITED UNCHANGED [{self.scope_id}] {dotted_path}: "
                            f"old={old_val!r} == new={value!r}"
                        )
                    self._live_resolved[dotted_path] = value

                    # Update provenance for this field
                    self._live_provenance[dotted_path] = (source_scope_id, source_type)

        # Store for navigation only when recomputation observed concrete deltas.
        # First-populate paths legitimately have no resolved delta; preserving the
        # raw update_parameter() paths keeps time-travel/flash navigation precise.
        if changed_values:
            self._set_last_changed_values(changed_values)
        return self.notification_fields_for_value_changes(changed_values)

    @property
    def last_changed_field(self) -> Optional[str]:
        """Field that most recently changed value (not just dirty status).

        This tracks any value change regardless of saved/unsaved state,
        useful for time-travel navigation to show what changed in a transition.
        """
        return self._last_changed_field

    def reset_parameter(self, param_name: str) -> None:
        """Reset parameter to signature default (None for lazy dataclasses).

        Delegates to update_parameter() to ensure consistent invalidation behavior.
        """
        if param_name not in self.parameters:
            return

        # Use signature defaults (CLASS defaults), not instance values
        # This ensures reset goes back to None for lazy fields, not saved concrete values
        default_value = self._signature_defaults.get(param_name)
        self.update_parameter(param_name, default_value)

    def signature_default(self, param_name: str) -> Any:
        """Return the signature default recorded for one flat parameter path."""
        if param_name not in self._signature_defaults:
            raise KeyError(
                f"No signature default recorded for parameter {param_name!r}."
            )
        return self._signature_defaults[param_name]

    def get_current_values(self) -> Dict[str, Any]:
        """
        Get current parameter values from state.

        With flat storage, this returns the flat dict with dotted paths.
        Callers needing nested structure should use to_object() instead.

        For ObjectState, this reads directly from self.parameters.
        PFM overrides this to also read from widgets.
        """
        # Auto-detect delegate changes before accessing parameters
        self._check_and_sync_delegate()
        return dict(self.parameters)

    def reconstruct_top_level_parameters(self) -> Dict[str, Any]:
        """Return top-level parameters with nested dataclass values rebuilt.

        ObjectState stores nested fields in a flat dotted-path mapping. Function
        pattern kwargs need the top-level call signature values, not the flat UI
        storage shape. This method exposes that boundary without requiring UI
        widgets or service code to reach into ObjectState private helpers.
        """
        self._check_and_sync_delegate()

        values: Dict[str, Any] = {}
        root_type = type(self._extraction_target)
        top_level_params = {
            key
            for key in self.parameters
            if "." not in key
        }

        for param_name in top_level_params:
            param_type = self._path_to_type.get(param_name)
            nested_dataclass = (
                param_type is not None
                and is_dataclass(param_type)
                and param_type != root_type
            )
            if nested_dataclass:
                values[param_name] = self._reconstruct_from_prefix(param_name)
            else:
                values[param_name] = self.parameters[param_name]

        return values

    # ==================== MATERIALIZED DIFFS ====================

    @property
    def dirty_fields(self) -> Set[str]:
        """Fields where resolved_live != resolved_saved."""
        return self._dirty_fields

    @property
    def signature_diff_fields(self) -> Set[str]:
        """Fields where raw != signature_default."""
        return self._signature_diff_fields

    @property
    def is_raw_dirty(self) -> bool:
        """Check if raw parameters differ from saved parameters (not resolved values)."""
        return self.parameters != self._saved_parameters

    def _update_raw_dirty(self) -> bool:
        """Recompute raw dirty state, return True if it changed."""
        new_raw_dirty = self.is_raw_dirty
        if new_raw_dirty != self._raw_dirty:
            self._raw_dirty = new_raw_dirty
            return True
        return False

    def _compute_dirty_fields(self) -> Set[str]:
        """Compute dirty set from live vs saved caches."""
        if self._live_resolved is None:
            return set()
        dirty = set()

        def _normalize_callable_value(value: Any) -> Any:
            if value is None:
                return None
            if callable(value):
                return value
            if isinstance(value, list):
                normalized = []
                for item in value:
                    if callable(item):
                        normalized.append(item)
                        continue
                    if isinstance(item, tuple) and len(item) == 2 and callable(item[0]) and isinstance(item[1], dict):
                        pruned_kwargs = {k: v for k, v in item[1].items() if v is not None}
                        normalized.append(item[0] if not pruned_kwargs else (item[0], pruned_kwargs))
                if len(normalized) == 1 and callable(normalized[0]):
                    return normalized[0]
                return normalized
            return value
        for k in (self._live_resolved.keys() | self._saved_resolved.keys()):
            live_val = _normalize_callable_value(self._live_resolved.get(k))
            saved_val = _normalize_callable_value(self._saved_resolved.get(k))

            if live_val != saved_val:
                dirty.add(k)
                logger.debug(f"🔴 DIRTY_FIELD: scope={self.scope_id!r} field={k!r} live={live_val!r} saved={saved_val!r}")
        if dirty:
            logger.debug(f"🔴 DIRTY_SUMMARY: scope={self.scope_id!r} dirty_fields={dirty}")
        return dirty

    def _compute_signature_diff_fields(self) -> Set[str]:
        """Compute signature-diff set from parameters vs defaults.

        Any field that differs from its signature default is included.
        Nested dataclass container fields are implicitly excluded since
        they don't have entries in _signature_defaults (only leaf fields do).
        """
        result = set()
        for k, v in self.parameters.items():
            if k in self._signature_defaults:
                # Direct dict key access - no special behavior to avoid
                sig_default = self._signature_defaults[k]
                is_diff = v != sig_default
                if is_diff:
                    result.add(k)
        return result

    def _update_dirty_fields(self) -> Set[str]:
        """Recompute _dirty_fields, return set of fields that changed dirty status.

        Returns fields that either became dirty OR became clean.
        Empty set means no change.
        """
        new_dirty = self._compute_dirty_fields()
        if new_dirty != self._dirty_fields:
            # Symmetric difference: fields that changed dirty status in either direction
            changed_fields = new_dirty ^ self._dirty_fields
            self._dirty_fields = new_dirty
            return changed_fields
        return set()

    def _update_signature_diff_fields(self) -> bool:
        """Recompute _signature_diff_fields, return True if changed."""
        new_sig_diff = self._compute_signature_diff_fields()
        if new_sig_diff != self._signature_diff_fields:
            self._signature_diff_fields = new_sig_diff
            return True
        return False

    def _sync_materialized_state(
        self,
        *,
        changed_value_fields: Set[str] | None = None,
        emit_notifications: bool = True,
    ) -> bool:
        """Single point where materialized diffs are recomputed and notified.

        Call this after ANY mutation that could affect:
        - _live_resolved (affects dirty_fields)
        - _saved_resolved (affects dirty_fields)
        - parameters (affects signature_diff_fields)

        Correctness guarantee: All mutation paths call this ONE method.

        Flash behavior: Fires on_resolved_changed for fields that changed value
        and fields that changed dirty status. This ensures flash animation
        triggers for edits within an already-dirty value, not just clean/dirty
        transitions.
        """
        raw_dirty_changed = self._update_raw_dirty()
        dirty_status_changed_fields = self._update_dirty_fields()
        sig_diff_changed = self._update_signature_diff_fields()
        notification_fields = self._most_specific_notification_fields(
            dirty_status_changed_fields | (changed_value_fields or set())
        )

        materialized_changed = raw_dirty_changed or bool(notification_fields) or sig_diff_changed
        if materialized_changed:
            ObjectStateRegistry.mark_snapshot_dirty_scope(self.scope_id)

        if emit_notifications:
            self._notify_resolved_changed(
                notification_fields,
                context="_sync_materialized_state",
            )

            if materialized_changed:
                self._notify_state_changed(notification_fields)

        return materialized_changed

    def prepare_for_snapshot_capture(self) -> None:
        """Synchronize only pending resolved work before immutable capture."""
        if self._live_resolved is not None and not self._invalid_fields:
            return

        changed_paths = self._ensure_live_resolved(notify_flash=False)
        self._sync_materialized_state(
            changed_value_fields=changed_paths,
            emit_notifications=False,
        )

    # ==================== SAVED STATE / DIRTY TRACKING ====================

    def _compute_resolved_snapshot(self, use_saved: bool = False) -> Dict[str, Any]:
        """Resolve all fields for this state into a snapshot dict.

        PERFORMANCE: Build context stack ONCE and resolve ALL fields in bulk (not per-field).

        UNIFIED: Works for ANY object_instance type (dataclass, class instance, callable).
        Root object type doesn't matter - we iterate paths and check _path_to_type for each.

        Args:
            use_saved: If True, resolve using saved baselines (object_instance) instead of
                       live state (to_object()). Used for computing _saved_resolved to ensure
                       saved baseline only depends on other saved baselines.
        """
        from objectstate.context_manager import build_context_stack
        from objectstate.dual_axis_resolver import resolve_with_provenance
        from objectstate.lazy_factory import has_lazy_resolution

        if not isinstance(self.parameters, dict):
            raise TypeError(
                "ObjectState.parameters must remain a canonical flat dictionary."
            )
        if not isinstance(self._saved_parameters, dict):
            raise TypeError(
                "ObjectState._saved_parameters must remain a canonical flat dictionary."
            )

        # Get ancestor objects WITH scope_ids for provenance tracking
        # use_saved=True returns object_instance (saved), False returns to_object() (live)
        ancestor_objects_with_scopes = ObjectStateRegistry.get_ancestor_objects_with_scopes(
            self.scope_id, use_saved=use_saved
        )

        # Use saved baseline or live state for this object
        if use_saved:
            # Use saved_object which handles delegation correctly
            current_obj = self.saved_object
        else:
            # CRITICAL: Use to_object() to get CURRENT state with user edits,
            # not object_instance which is the original/saved baseline.
            current_obj = self.to_object(update_delegate=False)

        # Build context stack ONCE with scope_ids for provenance tracking
        # CRITICAL: use_live must match use_saved to ensure global config layer
        # uses SAVED thread-local when computing saved baselines
        stack = build_context_stack(
            object_instance=current_obj,
            ancestor_objects_with_scopes=ancestor_objects_with_scopes,
            current_scope_id=self.scope_id,
            use_live=not use_saved,
        )

        snapshot: Dict[str, Any] = {}
        provenance: Dict[str, Tuple[Optional[str], Optional[type]]] = {}

        # CRITICAL: When computing saved_resolved, use _saved_parameters for raw values.
        # This ensures saved_resolved represents "what was last saved locally" + ancestor saved values,
        # NOT "current live edits resolved with saved ancestor context".
        # This is key for dirty detection: dirty = live_resolved != saved_resolved
        #
        params_source = self._saved_parameters if use_saved else self.parameters

        # UNIFIED: Resolve ALL fields in single context stack
        # For each path, check if it has a lazy dataclass container type
        with stack:
            for dotted_path in self.parameters.keys():
                raw_value = params_source.get(dotted_path)
                container_type = self._path_to_type.get(dotted_path)
                parts = dotted_path.split('.')

                # Check if this path is a CONTAINER entry (value is a nested dataclass)
                # vs a LEAF field (value is primitive, even if container_type is a dataclass)
                is_container_entry = self._is_flat_container_parameter(
                    dotted_path,
                    raw_value,
                )

                if is_container_entry:
                    # Container-level entry - SKIP from snapshot
                    # Containers are kept in parameters for UI rendering but excluded from
                    # dirty comparison since we compare leaf fields instead
                    pass
                elif (
                    container_type is not None
                    and is_dataclass(container_type)
                    and has_lazy_resolution(container_type)
                ):
                    # Leaf field inside a LAZY dataclass - resolve value AND provenance in ONE walk
                    # CRITICAL: Only resolve for lazy dataclasses! Non-lazy dataclasses with None
                    # defaults should keep None as-is, not trigger inheritance resolution.
                    # This handles both:
                    # - Nested fields (processing_config.group_by) where parts > 1
                    # - Top-level fields on root (num_workers on PipelineConfig) where parts == 1
                    field_name = parts[-1]

                    if raw_value is None:
                        # Field needs resolution - use combined resolve + provenance walk
                        resolved_val, source_scope, source_type = resolve_with_provenance(container_type, field_name)
                        snapshot[dotted_path] = resolved_val

                        # Track provenance for inherited values (live only)
                        # Store (scope_id, source_type) tuple so UI can find the correct path
                        if not use_saved:
                            provenance[dotted_path] = (source_scope, source_type)
                    else:
                        # Field has concrete local value - no resolution needed
                        resolved_val = raw_value
                        snapshot[dotted_path] = resolved_val

                    logger.debug(
                        f"SNAPSHOT [{self.scope_id}] {dotted_path}: "
                        f"raw={raw_value!r} -> resolved={resolved_val!r} (type={type(resolved_val).__name__})"
                    )
                else:
                    # Non-lazy field (regular dataclass, class instance, callable) - use raw value directly
                    # None stays as None, no inheritance resolution
                    snapshot[dotted_path] = raw_value

        # Store provenance for live resolution (not saved)
        if not use_saved:
            self._live_provenance = provenance

        return snapshot

    def mark_saved(self) -> None:
        """Mark current state as saved baseline.

        UNIFIED: Works for any object_instance type.

        CRITICAL: Invalidates descendant caches for any parameters that changed.
        This ensures that when saving, other windows that inherited from the
        old saved values get their caches invalidated so they pick up new values.
        This mirrors what restore_saved() does but in the opposite direction.

        Invalidation is based on comparing the OLD object_instance (about to be replaced)
        with the NEW self.parameters (live values used for reconstruction).
        """
        logger.debug(f"🐛 mark_saved: ENTER for scope={self.scope_id!r}, obj_type={type(self.object_instance).__name__}, _saved_parameters is None={self._saved_parameters is None}")
        # Ensure live cache is populated for accurate dirty computation post-save
        self._ensure_live_resolved(notify_flash=False)

        # CRITICAL: Extract old values from object_instance BEFORE rebuilding it
        # These are the values that descendants might be inheriting from
        old_instance_values = {}
        if not isinstance(self.object_instance, type):
            # Extract raw attribute values from the old object_instance
            for param_name in self.parameters.keys():
                # Skip container entries (nested dataclass instances)
                if param_name in self.parameters:
                    raw_value = self.parameters.get(param_name)
                    if self._is_flat_container_parameter(param_name, raw_value):
                        continue

                # Get the old value by navigating dotted path on the extraction target
                # For delegation, parameters are on the delegate, not object_instance
                try:
                    # Navigate through nested attributes for dotted paths
                    obj = self._extraction_target
                    parts = param_name.split('.')
                    for part in parts:
                        obj = object.__getattribute__(obj, part)
                    old_instance_values[param_name] = obj
                except AttributeError:
                    # Field doesn't exist on extraction target, skip it
                    pass

        # Find parameters that differ between old object_instance and new live parameters
        # These are the fields that changed and need descendant invalidation
        changed_params = []
        for param_name in self.parameters.keys():
            # Skip container entries
            raw_value = self.parameters.get(param_name)
            if self._is_flat_container_parameter(param_name, raw_value):
                continue

            old_value = old_instance_values.get(param_name)
            new_value = self.parameters.get(param_name)
            if old_value != new_value:
                changed_params.append(param_name)

        # CRITICAL: Rebuild extraction target BEFORE invalidating descendants
        # Descendants will recompute using parent's extraction target, so it must have new values!
        if not isinstance(self.object_instance, type):
            if self._delegate_attr is not None:
                # DELEGATION: to_object() returns the delegate and updates it on object_instance
                # as a side effect. Keep object_instance unchanged (it's the lifecycle object).
                # _extraction_target is updated to point to the new delegate.
                self._extraction_target = self.to_object(update_delegate=True)
            else:
                # NON-DELEGATION: to_object() returns the reconstructed object_instance
                self.object_instance = self.to_object(update_delegate=True)
                self._extraction_target = self.object_instance  # Keep in sync

        # Update saved parameters (after object_instance update, before invalidation)
        self._saved_parameters = self._copy_parameters_for_saved_baseline()

        # NOW invalidate descendant caches AFTER object_instance is updated
        # This ensures descendants see the NEW object_instance when they recompute
        # CRITICAL: Also invalidate saved_resolved cache so descendants recompute their saved baseline
        logger.debug(f"🔧 mark_saved: Starting invalidation for changed_params={changed_params}, scope={self.scope_id!r}")
        for param_name in changed_params:
            container_type = self._path_to_type.get(param_name, type(self.object_instance))
            leaf_field_name = param_name.split('.')[-1] if '.' in param_name else param_name
            logger.debug(f"🔧 mark_saved: Invalidating param={param_name}, container_type={container_type.__name__ if hasattr(container_type, '__name__') else type(container_type).__name__}, leaf_field={leaf_field_name}")

            ObjectStateRegistry.invalidate_by_type_and_scope(
                scope_id=self.scope_id,
                changed_type=container_type,
                field_name=leaf_field_name,
                invalidate_saved=True  # Invalidate saved baseline for descendants
            )

        # Compute new saved resolved using SAVED ancestor baselines (use_saved=True)
        # This ensures saved baseline is computed relative to other saved baselines
        logger.debug(f"🔧 mark_saved: Computing new saved_resolved for scope={self.scope_id!r}")
        new_saved_resolved = self._compute_resolved_snapshot(use_saved=True)
        logger.debug(f"🔧 mark_saved: New saved_resolved computed, keys={list(new_saved_resolved.keys())[:5]}...")

        # Update saved resolved baseline
        self._saved_resolved = new_saved_resolved

        # Invalidate cached object so next to_object() call rebuilds
        self._cached_object = None

        # Sync materialized state (single point for dirty/sig_diff update + notification)
        self._sync_materialized_state()

        # Record snapshot for time-travel (registry-level) - ONLY if there were actual changes
        # This prevents no-op snapshots (e.g., saving a window where only sibling state changed)
        if changed_params:
            ObjectStateRegistry.record_snapshot("save", self.scope_id)

        # CRITICAL FIX: Propagate saved baseline update to ALL descendant states
        # When an ancestor's saved baseline changes, all descendants must recompute
        # their _saved_resolved to reflect the new ancestor saved values. This ensures that
        # when GlobalPipelineConfig is saved, plates/steps clear their dirty markers (*).
        logger.debug(f"🔧 mark_saved: Propagating saved baseline to descendants for scope={self.scope_id!r}")
        logger.debug(f"🔧 mark_saved: Total states in registry: {len(ObjectStateRegistry._states)}")
        
        # Collect descendant scopes first to avoid modifying registry during iteration.
        #
        # IMPORTANT: Global scope is represented by "" (empty string).
        # In that case, *every* non-global scope is a descendant, but the naive
        # prefix check ("" + "::" == "::") matches nothing.
        changed_scope = ObjectStateRegistry._normalize_scope_id(self.scope_id)
        if changed_scope == "":
            # Global baseline change affects ALL other states.
            descendant_scopes = [
                s.scope_id for s in ObjectStateRegistry._states.values()
                if ObjectStateRegistry._normalize_scope_id(s.scope_id) != ""
            ]
        else:
            prefix = changed_scope + "::"
            descendant_scopes = [
                s.scope_id for s in ObjectStateRegistry._states.values()
                if s.scope_id is not None and ObjectStateRegistry._normalize_scope_id(s.scope_id).startswith(prefix)
            ]
        logger.debug(f"🔧 mark_saved: Found {len(descendant_scopes)} descendant scopes: {descendant_scopes}")
        
        for descendant_scope in descendant_scopes:
            state = ObjectStateRegistry._states.get(descendant_scope)
            if state is not None:
                logger.debug(f"🔧 mark_saved: Processing descendant state scope={descendant_scope!r}, obj_type={type(state.object_instance).__name__}")
                logger.debug(f"🐛 mark_saved descendant: _saved_parameters is None={state._saved_parameters is None}, parameters is None={state.parameters is None}")
                # Log dirty fields BEFORE recompute
                logger.debug(f"🔧 mark_saved: BEFORE recompute - dirty_fields={state._dirty_fields}, _saved_resolved_keys={list(state._saved_resolved.keys())[:3]}")
                # Recompute descendant's saved_resolved using new ancestor saved values
                try:
                    state._saved_resolved = state._compute_resolved_snapshot(use_saved=True)
                except AttributeError as e:
                    logger.error(f"🐛 mark_saved descendant: ERROR in _compute_resolved_snapshot for scope={descendant_scope!r}! Error: {e}")
                    logger.error(f"🐛 mark_saved descendant: state._saved_parameters type={type(state._saved_parameters).__name__}, is None={state._saved_parameters is None}")
                    logger.error(f"🐛 mark_saved descendant: state.parameters type={type(state.parameters).__name__}, is None={state.parameters is None}")
                    raise
                # Sync materialized state so dirty fields are recalculated
                state._sync_materialized_state()
                # Log dirty fields AFTER recompute
                logger.debug(f"🔧 mark_saved: AFTER recompute - dirty_fields={state._dirty_fields}, _saved_resolved_keys={list(state._saved_resolved.keys())[:3]}")
            else:
                logger.warning(f"🔧 mark_saved: Descendant scope {descendant_scope!r} not found in registry!")

    def restore_saved(self, *, propagate_descendants: bool = True) -> None:
        """Restore parameters to the last saved baseline (from object_instance).

        UNIFIED: Works for any object_instance type.

        CRITICAL: Invalidates descendant caches for any parameters that changed.
        This ensures that when closing a window without saving, other windows
        that inherited from the unsaved values get their caches invalidated.

        Also emits on_resolved_changed for THIS state so same-level observers
        (like list items subscribed to this ObjectState) flash when values revert.
        """
        if isinstance(self.object_instance, type):
            self.invalidate_cache()
            self._sync_materialized_state()
            return

        # If there are no unsaved edits, restoring is a semantic no-op and should not
        # create time-travel snapshots (noise).
        if not self.is_raw_dirty:
            return

        # Coalesce all restore side-effects into a single snapshot
        with ObjectStateRegistry.atomic(f"restore {self.scope_id}"):
            self._restore_saved_impl(propagate_descendants=propagate_descendants)
            return

    def _restore_live_global_context_from_saved(self) -> None:
        """Keep global live thread-local aligned after cancelling edits."""
        obj_type = type(self.object_instance)
        from objectstate.lazy_factory import is_global_config_type
        if not is_global_config_type(obj_type):
            return

        from objectstate.context_manager import clear_current_temp_global
        from objectstate.global_config import set_live_global_config

        set_live_global_config(obj_type, copy.deepcopy(self._extraction_target))
        clear_current_temp_global()

    def _restore_saved_impl(self, *, propagate_descendants: bool = True) -> None:
        """Internal restore implementation (wrapped by restore_saved atomic block)."""

        # Find parameters that differ from saved baseline AND capture their container types
        # BEFORE clearing parameters (we need _path_to_type)
        changed_params_with_types = []
        logger.debug(f"🐛 restore_saved: About to iterate parameters, _saved_parameters type={type(self._saved_parameters).__name__}, is None={self._saved_parameters is None}")
        for param_name, current_value in self.parameters.items():
            try:
                saved_value = self._saved_parameters.get(param_name)
            except AttributeError as e:
                logger.error(f"🐛 restore_saved: ERROR accessing _saved_parameters.get({param_name!r})! _saved_parameters type={type(self._saved_parameters).__name__}, is None={self._saved_parameters is None}, scope={self.scope_id!r}")
                raise
            if current_value != saved_value:
                container_type = self._path_to_type.get(param_name, type(self.object_instance))
                leaf_field_name = param_name.split('.')[-1] if '.' in param_name else param_name
                changed_params_with_types.append((param_name, container_type, leaf_field_name))

        # Clear and re-extract from the saved baseline
        # CRITICAL: For delegation, extract from the delegate (pipeline_config), not the lifecycle object.
        # This keeps flat parameters aligned with the form's target object after window close/reopen.
        # Also refresh _extraction_target in case the delegate attribute was replaced externally.
        extraction_target = self._extraction_target
        if self._delegate_attr is not None:
            try:
                extraction_target = getattr(self.object_instance, self._delegate_attr)
                self._extraction_target = extraction_target
            except Exception:
                # Fallback to existing extraction target if delegate access fails
                extraction_target = self._extraction_target
        self._replace_parameter_structure(
            extraction_target,
            exclude_params=self._exclude_param_names,
        )

        # CRITICAL: Also restore _saved_parameters to match current parameters
        # After restore, parameters == saved (both extracted from object_instance)
        self._saved_parameters = self._copy_parameters_for_saved_baseline()
        self._restore_live_global_context_from_saved()

        self.invalidate_cache()
        # Invalidate cached reconstructed object (may contain unsaved edits)
        self._cached_object = None
        self._cached_object_applied = False

        # CRITICAL: Recompute _saved_resolved to match the restored state
        # Time travel may have overwritten _saved_resolved with snapshot values,
        # but after restore_saved(), _saved_resolved should reflect object_instance
        self._saved_resolved = self._compute_resolved_snapshot(use_saved=True)

        # Recompute _live_resolved to reflect any unsaved changes from higher-level ObjectStates
        # This ensures that unsaved resolved changes from other windows are preserved
        self._live_resolved = self._compute_resolved_snapshot(use_saved=False)

        # NOW invalidate descendant caches for each changed parameter
        # This must happen AFTER restoring parameters so descendants see restored values
        for param_name, container_type, leaf_field_name in changed_params_with_types:
            ObjectStateRegistry.invalidate_by_type_and_scope(
                scope_id=self.scope_id,
                changed_type=container_type,
                field_name=leaf_field_name
            )

        # Optionally propagate restore to descendant ObjectStates so their parameters reflect saved baseline.
        #
        # This is important when restoring a parent that *owns* descendant parameter state (e.g. Step -> function
        # ObjectStates) so canceling the parent edit resets child ObjectStates.
        #
        # However, for delegation-based parents that act as context providers (e.g. orchestrator -> pipeline_config),
        # restoring the parent should generally *not* restore descendant raw parameters (steps). Descendants should
        # only have their resolved caches invalidated so they re-resolve against the restored context.
        if propagate_descendants:
            descendant_scopes = [
                scope
                for scope in ObjectStateRegistry._states.keys()
                if scope.startswith(f"{self.scope_id}::")
            ]
            for descendant_scope in descendant_scopes:
                state = ObjectStateRegistry._states.get(descendant_scope)
                if state:
                    state._restore_saved_impl(propagate_descendants=True)

        # Emit on_resolved_changed for changed params so SAME-LEVEL observers flash
        # (e.g., list item subscribed to this ObjectState sees the revert as a change)
        did_atomic_restore = False
        if changed_params_with_types:
            changed_paths = {param_name for param_name, _, _ in changed_params_with_types}
            # Coalesce any updates triggered by callbacks into a single snapshot
            if self._parent_state is None:
                with ObjectStateRegistry.atomic(f"restore {self.scope_id}"):
                    self._notify_resolved_changed(
                        changed_paths,
                        context="restore_saved",
                    )
                did_atomic_restore = True
            else:
                self._notify_resolved_changed(
                    changed_paths,
                    context="restore_saved",
                )

        # Sync materialized state (single point for dirty/sig_diff update + notification)
        self._sync_materialized_state()

        # Record snapshot for time-travel (registry-level) - ONLY if there were changes
        if changed_params_with_types and not did_atomic_restore:
            ObjectStateRegistry.record_snapshot("restore", self.scope_id)

    def should_skip_updates(self) -> bool:
        """Check if updates should be skipped due to batch operations."""
        return self._in_reset or self._block_cross_window_updates

    # ==================== FLAT STORAGE METHODS (NEW) ====================

    def _extract_all_parameters_flat(self, obj: Any, prefix: str = '', exclude_params: Optional[List[str]] = None) -> None:
        """Recursively extract parameters into flat dict with dotted paths.

        Populates self.parameters, self._path_to_type, and self._parameter_descriptions with dotted path keys.

        Uses pluggable parameter analyzer if available, falls back to stdlib dataclass introspection.

        Args:
            obj: Object to extract from (dataclass instance, callable, or regular object)
            prefix: Current path prefix (e.g., 'well_filter_config')
            exclude_params: List of top-level parameter names to exclude
        """
        exclude_params = exclude_params or []

        obj_type = type(obj)
        is_function = isinstance(obj, FunctionType)
        owner_target: ParameterOwner = obj if is_function else obj_type

        # Delegate signature default extraction to python_introspect (it must derive
        # defaults from the type/signature and avoid instance attribute reads).
        param_info = self._analyze_parameters(obj, exclude_params if not prefix else [])

        logger.debug(f"🔧 _extract_all_parameters_flat: obj_type={obj_type.__name__}, prefix={prefix!r}, param_info keys={list(param_info.keys())}")

        for param_name, info in param_info.items():
            # Skip excluded parameters (only at top level)
            if not prefix and param_name in exclude_params:
                continue

            # Build dotted path
            dotted_path = f'{prefix}.{param_name}' if prefix else param_name

            # Get current value
            if is_function:
                # For functions: use signature default from UnifiedParameterAnalyzer
                # (functions don't have instance attributes)
                current_value = info.default_value
            else:
                # For class instances: bypass lazy resolution via object.__getattribute__
                try:
                    current_value = object.__getattribute__(obj, param_name)
                except AttributeError:
                    current_value = info.default_value

            # Store description entry for the dotted path. Even if the specific
            # parameter has no description, ensure the dotted key exists so
            # callers can rely on presence of the full path (value may be None).
            self._parameter_descriptions[dotted_path] = getattr(info, 'description', None)

            # Check if this is a nested dataclass
            # First try from type annotation, then fall back to checking actual value
            nested_type = self._get_nested_dataclass_type(info.param_type)

            # A registered lazy runtime value owns its raw reconstruction type.
            # The enclosing annotation commonly names the concrete base config,
            # but reconstructing unresolved ``None`` sentinels through that base
            # would run concrete validation before inheritance resolution.
            if current_value is not None:
                value_type = type(current_value)
                if is_dataclass(value_type):
                    from objectstate.lazy_factory import get_base_type_for_lazy

                    if (
                        nested_type is None
                        or get_base_type_for_lazy(value_type) is not None
                    ):
                        nested_type = value_type

            if nested_type is not None and current_value is not None:
                # Store the nested config type reference at this path
                self._path_to_type[dotted_path] = nested_type

                # Store the nested dataclass instance in parameters (needed for UI rendering)
                self.parameters[dotted_path] = current_value

                # Container resets follow the same declared-default authority as
                # leaf resets. Lazy dataclass fields retain their intentional
                # ``None`` default, while callable parameters with concrete
                # dataclass defaults can be restored after an authored override
                # is removed.
                self._signature_defaults[dotted_path] = info.default_value

                # Recurse into nested dataclass for child fields
                self._extract_all_parameters_flat(current_value, prefix=dotted_path, exclude_params=[])
            else:
                # Leaf field - store value and container type
                self.parameters[dotted_path] = current_value
                # Store the owner target that has this field.
                self._path_to_type[dotted_path] = owner_target
                # Store signature default for reset functionality (flattened)
                # info.default_value is now guaranteed to be the CLASS signature default
                self._signature_defaults[dotted_path] = info.default_value

    def _replace_parameter_structure(
        self,
        obj: Any,
        *,
        exclude_params: list[str] | None = None,
        initial_values: dict[str, Any] | None = None,
    ) -> None:
        """Extract one canonical flat parameter structure and index it once."""

        self.parameters.clear()
        self._path_to_type.clear()
        self._signature_defaults.clear()
        self._parameter_descriptions.clear()
        self._extract_all_parameters_flat(
            obj,
            prefix="",
            exclude_params=exclude_params,
        )
        if initial_values:
            for param_name, value in initial_values.items():
                self.parameters[param_name] = value
                self.parameters.update(
                    self._dataclass_parameter_updates(param_name, value)
                )
        self._index_parameter_paths()

    def _index_parameter_paths(self) -> None:
        """Index immutable direct-child topology from canonical flat parameters."""

        paths_by_owner: dict[DottedFieldPath, list[DottedFieldPath]] = {}
        for dotted_path in self.parameters:
            owner_path, separator, _field_name = dotted_path.rpartition(".")
            if not separator:
                owner_path = ""
            paths_by_owner.setdefault(DottedFieldPath(owner_path), []).append(
                DottedFieldPath(dotted_path)
            )
        self._direct_parameter_paths = {
            owner_path: tuple(parameter_paths)
            for owner_path, parameter_paths in paths_by_owner.items()
        }

    def to_object(self, *, update_delegate: bool = False, sync_delegate: bool = True) -> Any:
        """Reconstruct object from flat parameters with updated nested configs.

        BOUNDARY METHOD - EXPENSIVE - only call at system boundaries:
        - Save operation
        - Execute operation
        - Serialization

        UNIFIED: Works for ANY object_instance type.
        - Python functions: can't copy, return original
        - Everything else: shallow copy + reconstruct nested dataclass fields

        DELEGATION: If __objectstate_delegate__ was used:
        - Reconstructs the delegate (e.g., pipeline_config)
        - If update_delegate=True, updates the delegate attribute on object_instance
        - Returns the reconstructed delegate (NOT object_instance)
        - Callers needing the lifecycle object (orchestrator) should use state.object_instance

        Args:
            update_delegate: If True, apply reconstructed delegate to object_instance
            sync_delegate: If True (default), check for delegate changes before reconstruction.
                          Set to False during cache recomputation to avoid re-entrant invalidation.

        Returns:
            The reconstructed object that matches the stored parameters.
            For delegation, this is the delegate type (config), not the lifecycle object.
        """
        # Auto-detect delegate changes before reconstruction (unless explicitly disabled)
        if sync_delegate:
            self._check_and_sync_delegate()

        if self._cached_object is not None:
            if not update_delegate:
                return self._cached_object
            if self._delegate_attr is None or self._cached_object_applied:
                return self._cached_object
            # Apply cached delegate to lifecycle object when requested
            setattr(self.object_instance, self._delegate_attr, self._cached_object)
            self._cached_object_applied = True
            return self._cached_object

        # UNIFIED: reconstruct nested dataclass fields
        # Works for dataclass, non-dataclass class instances, AND functions
        import copy

        # For delegation, work with the extraction target (delegate), not object_instance
        target = self._extraction_target

        # Collect ALL top-level field updates from self.parameters
        # This includes both primitive fields AND nested dataclass fields
        field_updates = {}
        root_type = type(target)
        for field_name in self._path_to_type:
            if '.' not in field_name:
                # Check if this field's TYPE is a dataclass (not the instance value)
                # We need to check the TYPE because the instance value might be stale
                # (e.g., self.parameters['well_filter_config'] might have well_filter=2
                # even though self.parameters['well_filter_config.well_filter'] = None)
                field_type = self._path_to_type.get(field_name)
                # CRITICAL FIX: _path_to_type stores CONTAINER type for leaf fields,
                # but FIELD type for nested dataclass fields. We must distinguish:
                # - If field_type == root_type, it's a leaf field (container type stored)
                # - If field_type != root_type AND is_dataclass, it's a nested dataclass
                is_nested_dataclass = (
                    field_type is not None and
                    is_dataclass(field_type) and
                    field_type != root_type  # Not the container type
                )
                if is_nested_dataclass:
                    # Nested dataclass: ALWAYS recursively reconstruct from flat storage
                    # This ensures we pick up changes to nested fields like 'well_filter_config.well_filter'
                    logger.debug(f"🔧 to_object: Reconstructing nested dataclass '{field_name}' from flat storage")
                    reconstructed = self._reconstruct_from_prefix(field_name)
                    logger.debug(f"🔧 to_object: Reconstructed '{field_name}' type={type(reconstructed).__name__}")
                    # Log some field values for debugging
                    if hasattr(reconstructed, 'enabled'):
                        logger.debug(f"🔧 to_object: '{field_name}'.enabled = {reconstructed.enabled}")
                    field_updates[field_name] = reconstructed
                else:
                    # Primitive field: use value directly from parameters
                    value = self.parameters.get(field_name)
                    field_updates[field_name] = value

        # Reconstruct the target object (either object_instance or delegate)
        reconstructed = None

        # Python functions can't be copied, but we CAN update their attributes
        # This is critical for MRO resolution to see edited config values
        if isinstance(target, FunctionType):
            for field_name, field_value in field_updates.items():
                setattr(target, field_name, field_value)
            reconstructed = target
        elif is_dataclass(target):
            # CRITICAL: Use replace_raw to preserve raw None values!
            # dataclasses.replace triggers lazy resolution via __getattribute__,
            # which resolves None -> concrete defaults and breaks inheritance.
            from objectstate.lazy_factory import replace_raw
            reconstructed = replace_raw(target, **field_updates)
        else:
            # Non-dataclass class instance - shallow copy + setattr
            obj_copy = copy.copy(target)
            obj_type = type(target)
            for field_name, field_value in field_updates.items():
                # Skip read-only properties (those without setters)
                prop = getattr(obj_type, field_name, None)
                if isinstance(prop, property) and prop.fset is None:
                    continue
                setattr(obj_copy, field_name, field_value)
            reconstructed = obj_copy

        # DELEGATION: If using delegation, update the delegate attribute on object_instance
        # as a side effect, but return the reconstructed delegate (not object_instance).
        # This ensures callers get the correct type (config, not orchestrator).
        # Callers who need the lifecycle object should access state.object_instance directly.
        if self._delegate_attr is not None:
            if update_delegate:
                setattr(self.object_instance, self._delegate_attr, reconstructed)
                self._cached_object_applied = True
            else:
                self._cached_object_applied = False
            # Return the reconstructed delegate - this is what the parameters represent
            self._cached_object = reconstructed
        else:
            # NON-DELEGATION: Update object_instance to point to reconstructed object
            # This ensures that when to_object() is called (e.g., on window save),
            # the ObjectState automatically points to the new instance
            if update_delegate:
                self.object_instance = reconstructed
                self._extraction_target = reconstructed
                logger.debug(f"Auto-updated object_instance to new reconstructed object for scope={self.scope_id!r}")
            self._cached_object = reconstructed
            self._cached_object_applied = True

        return self._cached_object

    def _reconstruct_from_prefix(self, prefix: str) -> Any:
        """Recursively reconstruct dataclass from flat parameters.

        Args:
            prefix: Current path prefix (e.g., 'well_filter_config')

        Returns:
            Reconstructed dataclass instance
        """
        return self._reconstruct_from_parameter_snapshot(prefix, self.parameters)

    def _reconstruct_from_parameter_snapshot(
        self,
        prefix: str,
        parameters: Dict[str, Any],
    ) -> Any:
        """Recursively reconstruct dataclass from a flat parameter snapshot."""
        # Determine the type to reconstruct
        if not prefix:
            # Root level - use extraction target type (handles delegation)
            obj_type = type(self._extraction_target)
        else:
            # Nested level - look up type from _path_to_type
            obj_type = self._path_to_type.get(prefix)
            if obj_type is None:
                raise ValueError(f"No type mapping for prefix: {prefix}")

        prefix_dot = f'{prefix}.' if prefix else ''

        # Collect direct fields and nested prefixes
        direct_fields = {}
        nested_prefixes = set()

        for path, value in parameters.items():
            if not path.startswith(prefix_dot):
                continue

            remainder = path[len(prefix_dot):]

            if '.' in remainder:
                # This is a nested field - collect the first component
                first_component = remainder.split('.')[0]
                nested_prefixes.add(first_component)
            else:
                # Direct field of this object
                direct_fields[remainder] = value
                # DEBUG
                if prefix == 'well_filter_config' and remainder == 'well_filter':
                    logger.debug(f"🔍 _reconstruct: Found direct field {prefix}.{remainder} = {value}")

        # Reconstruct nested dataclasses first
        for nested_name in nested_prefixes:
            nested_path = f'{prefix_dot}{nested_name}'
            nested_obj = self._reconstruct_from_parameter_snapshot(
                nested_path,
                parameters,
            )
            direct_fields[nested_name] = nested_obj

        # CRITICAL: Do NOT filter out None values!
        # None can be a semantic value, such as "inherit from parent context".
        # When a user explicitly resets a field to None, we MUST pass that None
        # to the dataclass constructor so lazy resolution can walk up the MRO.
        # Filtering None would cause the dataclass to use its class-level default
        # instead of the user's explicit None, breaking inheritance.

        # At root level, include constructor params excluded from editing.
        if not prefix:
            direct_fields.update(self._excluded_params)

        # DEBUG: Log what we're reconstructing
        if prefix == 'well_filter_config':
            logger.debug(f"🔍 _reconstruct_from_prefix: prefix={prefix}, direct_fields={direct_fields}")

        # Instantiate the dataclass with ALL fields including None values
        result = obj_type(**direct_fields)

        # DEBUG: Log the result
        if prefix == 'well_filter_config':
            raw_well_filter = object.__getattribute__(result, 'well_filter')
            logger.debug(f"🔍 _reconstruct_from_prefix: Reconstructed {prefix} with well_filter={raw_well_filter}")

        return result

    def _get_changed_params_with_types(
        self, old_target: Any, new_target: Any
    ) -> List[Tuple[str, type, str]]:
        """
        Compare old and new extraction targets to find changed parameters.

        Returns a list of tuples: (param_name, container_type, leaf_field_name)
        """
        changed_params = []

        # Get all parameter names from the new extraction target
        for param_name in self.parameters.keys():
            old_value = self._get_param_value_from_target(old_target, param_name)
            new_value = self._get_param_value_from_target(new_target, param_name)

            if old_value != new_value:
                container_type = self._path_to_type.get(param_name, type(self.object_instance))
                leaf_field_name = param_name.split('.')[-1] if '.' in param_name else param_name
                changed_params.append((param_name, container_type, leaf_field_name))

        return changed_params

    def _get_param_value_from_target(self, target: Any, param_name: str) -> Any:
        """
        Get a parameter value from an extraction target by dotted path.

        Handles nested dataclass attributes.
        """
        if target is None:
            return None

        parts = param_name.split('.')
        current = target

        for part in parts:
            if not hasattr(current, part):
                return None
            current = getattr(current, part)

        return current
