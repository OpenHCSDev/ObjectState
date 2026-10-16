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
acceptance are unfinished. That checkpoint also exposed the default manager's
color-scheme failure. PyQt `ef7243c` fixes its actual cause: DerivationContext
copied an unused None over ParameterFormConfig's resolved scheme. The competing
slot is deleted. Default and explicitly configured schemes pass the real builder.

The following #46 producer prototype is deliberately unready for installation:

- `state.field(Settings, "text")`, `state.fields.text`, and
  `state.fields.bind(Settings, ("text",))` admit a declaration before use.
- Handles own `raw`, `value`, `default`, `write`, `reset`, `dirty`, `inspect`,
  `subscribe` and `subscribe_value`. Subscriptions return their release operation
  and deliver field handles, not path strings.
- FieldNamespace owns declaration discovery and subscription lifetime behavior
  shared by FieldProxy and RootFields. A root is a namespace, not a declared
  field: it no longer falsely advertises a field default/value contract. A root
  declaration literally named `value` can therefore be acquired normally.
- The old producer get_resolved_value/update_parameter/reset_parameter,
  public parameters storage, and on/off observer entry points are removed.
  Producer checkpoint/registry/inspection/edit-session consumers were migrated.
- A fresh producer editing session checks read/write/reset/dirty, leaf/root
  subscription delivery and release, inspection and rejection of a nonexistent
  declaration. This does NOT establish all applications work.
- Declaration lifetime is now tied to state + declaring owner + address, not a
  temporary ParameterStructure instance. Restore, same-schema replacement and
  actual registered-history undo retain the original handle; a same-name field
  on an unrelated declaration cannot be targeted through it.
- ParameterStructure.declare is the sole owner_paths writer. The index contains
  declaration owners only. Payload types come from the projection. The mixed
  _path_to_type alias, duplicate partial resolver and competing type-based
  reconstruction decisions are deleted. Full and targeted reads share one
  resolver, including descendant invalidation when a container becomes None,
  Inherit or Unset. Retained child drafts cannot override that container.
- Eleven focused producer tests pass. The source-paired bridge mutation/catalog
  journey preserves null, empty string and string 'None', resets to inheritance,
  rejects an unknown address and travels backward through registered history
  while retaining the original field handle.
- **Remaining bridge defect, owned by doctrine:** an omitted mutation value
  still defaults to None in the request DTO. Omission must be admitted as absence
  and rejected before mutation unless reset was requested; explicit JSON null
  must remain data. This needs repair at the existing request/codec boundary.
- Toad #687 now consumes handles throughout forms, saved preferences and sort
  subscriptions. Its forms are keyed by handles and release observers on unmount.
  Nullable inputs commit real values rather than checking a box over backend
  None; hints stay placeholders, never stored input. Annotated optional members
  retain their metadata. Twenty-four form/settings tests pass. A real source-
  paired Textual journey covers native clicks/keystrokes, null, empty/string
  'None', open refresh, registered undo and unmount release.
- PyQt `ef7243c` consumes handles in the real form manager and mutation pipeline.
  FieldWriteEvent and FieldResetEvent own their distinct operations; the common
  stage invokes one mutation. Deleted per-widget reset copies, duplicate root-
  path assembly, the duplicate native-input pipeline, and the unused initial-
  values mirror. Enabled paint and ancestor effects derive from backend fields,
  not checkbox paint or None-to-True fallback. One owner traverses the subtree;
  its last-painted effective state includes ancestor changes. Scope-owned
  observer releases and nested signal-block restoration are exercised.
  Six focused Qt cases pass, including real default-manager construction,
  native typing/reset clicks, one hook/publication, nullable and absent values,
  stale checkbox paint, open/nested backend enable changes and disposal.
- Dirty/path metadata APIs and full Qt/OpenHCS/Core ports remain unfinished.
  Qt window/list/bridge callers still need migration; OpenHCS still targets the
  preceding #32 producer checkpoint. Do not install the current branch heads as
  a finished paired stack.

Evidence is owned by doctrine-segment under
`/home/ts/.cache/agent-scratch/objectstate-declared-fields/`:
`handles-before.json` (NRA imports/attributes/calls and complete class census),
`handle-producer-declared-live.txt`, `declaration-owner-projection-live.txt`,
`declared-field-handles-final-tests.txt`, `bridge-handle-history-journey.txt`,
`form-manager-owner-journey.txt`, `reconstruction-live.txt`, and
`source-state-roundtrip-paired.txt`. Latest namespace/Toad receipts are
`namespace-admission-final-tests.txt`, `toad-nullable-annotation-final-tests.txt`
and `toad-nullable-annotation-final-journey.txt`. Qt receipts are
`qt-handle-mutation-owner-journey.txt` and `qt-field-reset-enabled-final-tests.txt`;
`qt-handle-consumers.txt` records the original selected caller census, and the
NRA transformations remain under the producer checkout's owned `.scratch/`.
Bridge verification additionally pairs the
existing zmqruntime source because the installed package lacks execution.config.
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
