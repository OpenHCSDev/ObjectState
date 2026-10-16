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
