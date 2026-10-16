# Declared field values and handles (#32, #46)

## Contract and authorized migration

A public config field read returns its effective value. A concrete stored value,
including Python `None`, is already effective and never requests inheritance.
`Inherit()` requests the existing context/MRO resolver. `Unset()` means that no
value is available, not Python `None` and not a request to inherit. Stored reads
remain an explicit operation of `DataclassFieldAccess`; copying and source
writing use stored reads, not implicit effective reads.

This is an intentional API/data cutover, not a compatible second interpretation
of `None`. Existing lazy saved configs that used `None` for inheritance require
an explicit one-time migration on preserved copies before installation. Ordinary
nullable concrete fields are not rewritten. No legacy reader belongs in src.

## Existing owners and complete consumers

- `DataclassFieldAccess` owns stored dataclass access. Resolver, merge, raw copy,
  serialization and layer comparison consume it instead of private raw readers.
- `LazyMethodBindings` and the existing lazy factory own config field access and
  constructor defaults. Their inheritance defaults become `Inherit()` while the
  declared domain annotation retains whether `None` is an actual valid value.
- The existing one resolver in `dual_axis_resolver.py` owns context/MRO selection
  and source provenance. Inherit continues that selection; a concrete None stops
  it. Missing defaults return Unset, not None.
- `ContextLayerStack` owns the layers. Global-config editing starts from the
  declared-default global object rather than adding a live global layer then
  masking it with a None mode. Delete `mask_with_none` and constructor patching.
- `ObjectState` owns reset, raw/resolved snapshots, provenance and dirty state.
  Reset takes the recorded declaration default, which is Inherit for lazy fields.
  Code generation, inspection, structural leaves and source comparison derive the
  same state. The existing structural `MissingValue` is replaced by Unset; no
  duplicate missing-state spelling remains.
- OpenHCS, FormBridge, PyQt and Toad callers must distinguish inherited controls
  from a literal nullable value and stop patching constructors. Core consumers
  are included in the same source census.

## Field identity next (#46)

Extend existing declaration/topology and `FieldProxy` behavior, not a parallel
path registry. A declaration-bound field is validated on acquisition and owns
read, write, reset, dirty/provenance queries and subscriptions. All callbacks and
callers carry that field identity; dotted text is an external display/encoding
projection, not the writable API. Remove the old string write/reset/read and
subscription API in the same migration. Native-forms #61 remains separately owned;
its path topology changes must be integrated normally, not copied or edited in
its worktree.

## Working checkpoints (not completion)

The #32 checkpoint `0586f27`, FormBridge `4d12e1e`, and PyQt `fb1c044`
passed a real source-paired Qt form journey: literal None and inherited 77
remain distinct; an already open form receives a backend change to None;
native keystrokes commit through the existing debounce; the view disposes.
Source generation round-trips None/Inherit/Unset/zero. Installed pycodify lacks
`imported_name`, so this is paired-source evidence, not installed acceptance.
Nested/inline controls, all callers, legacy saved-source migration and installed
acceptance are unfinished. The no-config form-manager constructor also still
fails because its color scheme defaults to None; the real application supplies
a ColorScheme. Doctrine owns follow-through on that discovered default defect.

The following #46 producer prototype is deliberately unready for installation:

- `state.field(Settings, "text")`, `state.fields.text`, and
  `state.fields.bind(Settings, ("text",))` admit a declaration before use.
- Handles own `raw`, `value`, `default`, `write`, `reset`, `dirty`, `inspect`,
  `subscribe` and `subscribe_value`. Subscriptions return their release operation
  and deliver field handles, not path strings.
- RootFields inherits declaration discovery and subscription lifetime behavior;
  only its live root schema and changed-field projection differ.
- The old producer get_resolved_value/update_parameter/reset_parameter,
  public parameters storage, and on/off observer entry points are removed.
  Producer checkpoint/registry/inspection/edit-session consumers were migrated.
- A fresh producer editing session checks read/write/reset/dirty, leaf/root
  subscription delivery and release, inspection and rejection of a nonexistent
  declaration. This does NOT establish all applications work.
- **Known structural gap:** handles currently retain a ParameterStructure
  identity. Schema reconstruction/undo must not retire an otherwise unchanged
  declaration. Canonical declaration lifetime and the overloaded owner_paths
  index require repair in ParameterStructure before calling this API complete.
- Dirty/path metadata APIs and external consumer ports remain unfinished. The
  companion frontend branches still target the preceding #32 producer checkpoint;
  do not combine their source with the unready #46 producer head.

Evidence is owned by doctrine-segment under
`/home/ts/.cache/agent-scratch/objectstate-declared-fields/`:
`handles-before.json` (NRA imports/attributes/calls and complete class census),
`handle-producer-declared-live.txt`, `form-manager-owner-journey.txt`,
`reconstruction-live.txt`, and `source-state-roundtrip-paired.txt`.
AST coverage is lexical; dynamic bindings are not claimed resolved.

## Delivery order

1. Complete source/class/decision/caller census with existing NRA syntax/family
   tooling across ObjectState and its production consumers; report dynamic OPEN
   bindings rather than claiming an AST proves dispatch.
2. Migrate the state/default/resolution/copy/codegen/UI family coherently. Push a
   working #32 checkpoint and all consumer branches, without aliases or fallbacks.
3. Migrate the handle family and delete string APIs for #46.
4. Batch focused checks, then use the actual affected applications with preserved
   saved data/copies. Source tests, private installs and shared installed acceptance
   are separate claims. Codex retains shared installation ownership.
