# Declared field values and handles

## Field meaning

A public field read returns its effective value. A concrete stored value,
including Python `None`, is already effective and never requests inheritance.
`Inherit()` requests context/MRO resolution. `Unset()` means that no value is
available: it is neither Python `None` nor a request to inherit.

`FieldValue` owns resolution, overlay, conversion and source rendering for
these meanings. Domain conversions apply to concrete values, not directives.
A container's None/Inherit/Unset meaning takes precedence over retained child
drafts when reconstructing it.

`DataclassFieldAccess` owns stored dataclass access. Copying, serialization and
layer comparison use stored reads rather than implicit effective reads.
The resolver owns context/MRO selection and provenance: an inherited value
continues that selection; concrete None stops it.

Inspection retains `raw` and `resolved` as `FieldValue` members. The family is
dataclass-declared, so the existing declaration-aware JSON codec preserves
`Value(None)`, `Inherit()` and `Unset()` with distinct member tags. Consumers
invoke member behavior rather than transporting a value plus presence flags.
`ValueDeclaration.of(annotation)` compiles field behavior from the resolved
annotation, not from its payload. Its `admit(value)` preserves directives and
selects configuration, nullable, scalar and collection behavior. Leaves have no
configuration-child interface. Root constructor/function/instance namespaces
are admitted separately through `construction_binding.admit_target`.

`ParameterOwnerDeclaration` owns shared constructor declarations. Configuration
rebuilding outside keyword initialization requires the explicit
`ConfigurationRebuild.from_fields` capability. `InheritedDefault` is the single
metadata key for inherited defaults; `ValueDefault` and `FactoryDefault` own
materialization. Unknown default names raise `KeyError`; MRO traversal selects
only declarations that actually declare the field.

Type normalization uses python-introspect's public `resolve_declared_type`.
LazyFactory supplies its registered relation once; consumers do not repeat lazy
lookups, fallback expressions or normalization caches.

Lazy constructor defaults are `Inherit()` without changing whether the domain
annotation permits None. Required parameters without a value use `Unset()`.
Reset restores the declaration default; saved values are a separate baseline.
Global-config editing starts from declared defaults rather than masking live
values with None.

## Declaration-bound handles

`ParameterStructure` owns declarations, their owners and topology. A payload's
nominal type does not replace its declaration owner. Reconstruction uses that
shared topology for raw and resolved projections.

Acquire a validated field with `state.field(Settings, "text")`,
`state.fields.text`, or `state.fields.bind(Settings, ("text",))`. A handle owns:

- Stored `raw`, effective `value`, declaration `default` and `saved_value` reads.
- `write(value)`, `reset()`, dirty/signature queries and inspection/provenance.
- Raw-state `subscribe(callback)` and effective `subscribe_value(callback)`.
  Callbacks receive handles; subscription returns its release operation.

A handle identifies its state, declaration owner and address. Compatible
restoration, same-schema replacement and registered-history undo preserve that
identity. A same-name field on an unrelated declaration does not inherit it.

`FieldNamespace` shares declaration discovery and observer lifetime behavior.
`RootFields` and `FieldProxy` are sibling capabilities: a root is a namespace,
not a field with a datum. A root declaration named `value` is therefore valid.
Factories synchronize the current editing delegate before admitting an owner.

`DottedFieldPath.bind(state)` admits an external address once. Paths remain
useful for wire encoding, source documents and UI navigation; subsequent field
reads, mutations and subscriptions use the admitted handle.

## Saved source

There is no second runtime interpretation of None. Historical lazy configs
that used None for inheritance need an explicit migration on preserved copies;
ordinary nullable concrete values must not be rewritten. Source generation
preserves literal None, inheritance, absence and empty lazy objects distinctly.
