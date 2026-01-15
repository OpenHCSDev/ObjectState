# ObjectState Documentation Audit

## Summary
Found **3 critical documentation bugs** in README.md where examples reference non-existent API methods.

## Issues Found

### ❌ Issue 1: `undo()` and `redo()` methods don't exist
**Location**: README.md lines 124-125
**Current (WRONG)**:
```python
ObjectStateRegistry.undo()
ObjectStateRegistry.redo()
```

**Actual API**:
```python
ObjectStateRegistry.time_travel_back()  # Go one step back
ObjectStateRegistry.time_travel_forward()  # Go one step forward
```

**Fix**: Replace with correct method names

---

### ❌ Issue 2: `get_branch_history()` returns Snapshot objects, not with `.id` attribute
**Location**: README.md line 133
**Current (CORRECT)**: `history = ObjectStateRegistry.get_branch_history()`
**But line 134 is WRONG**:
```python
ObjectStateRegistry.time_travel_to_snapshot(history[5].id)
```

**Actual**: `Snapshot` objects DO have `.id` attribute ✓ (This is correct)

---

### ❌ Issue 3: Missing `atomic()` context manager documentation
**Location**: README.md lines 128-130
**Current**: Shows `atomic()` usage
**Status**: ✓ CORRECT - `atomic()` method exists and works as documented

---

## Additional Findings

### ✓ Correct API Methods (verified in code):
- `ObjectStateRegistry.register(state)` ✓
- `ObjectStateRegistry.unregister(state)` ✓
- `ObjectStateRegistry.get_by_scope(scope_id)` ✓
- `ObjectStateRegistry.get_all()` ✓
- `state.update_parameter(field, value)` ✓
- `state.save()` ✓
- `state.restore_saved()` ✓
- `ObjectStateRegistry.atomic(label)` ✓
- `ObjectStateRegistry.get_branch_history()` ✓
- `ObjectStateRegistry.time_travel_to_snapshot(id)` ✓
- `ObjectStateRegistry.time_travel_to_head()` ✓
- `ObjectStateRegistry.create_branch(name, description)` ✓
- `ObjectStateRegistry.switch_branch(name)` ✓
- `ObjectStateRegistry.list_branches()` ✓
- `ObjectStateRegistry.export_history_to_dict()` ✓
- `ObjectStateRegistry.import_history_from_dict(data)` ✓
- `ObjectStateRegistry.save_history_to_file(path)` ✓
- `ObjectStateRegistry.load_history_from_file(path)` ✓

### ✓ ObjectState class methods (verified):
- `state.dirty_fields` ✓
- `state.save()` ✓
- `state.restore_saved()` ✓
- `state.update_parameter(field, value)` ✓

## Recommended Fixes

1. **Replace `undo()`/`redo()` with `time_travel_back()`/`time_travel_forward()`**
2. **Add note about time-travel semantics** (not traditional undo/redo)
3. **Consider adding convenience aliases** if backward compatibility needed

## Status
Ready for implementation

