## Typed field members across the bridge boundary

Paired source checkpoints: ObjectState `1479884`, FormBridge `b7c4ad5`, PyQt `f0acb19`, OpenHCS `8d3bac264`. Not shared-installed and not completion of the wider field cutover.

### Owner and consumers

- `FieldInspection` retains `raw` and `resolved` as `FieldValue` members. The two null-presence properties are deleted.
- `FieldValue` is dataclass-declared. Unchanged python-introspect `MemberFamily` (main `a9428c3`) already owns tagged abstract-dataclass encoding/decoding. No new codec, wrapper, case roster or registry was added.
- Shared bridge semantic DTO fields carry members, not nullable values plus two booleans. The four compact-presence re-derivations and redundant action-field overrides are deleted. Compact serialization uses the declaration-aware codec before selecting keys, preserving `Value(None)`, empty/false/zero, `Inherit()` and `Unset()` tags even with previews.
- Payload exclusion yields explicit absence for an excluded datum and retains directives; previews remain bounded display metadata. No exclusion fabricates literal null.
- Field-list compaction maps concrete data through the member. OpenHCS help/rendering consume member behavior; the obsolete null-as-inheritance summary counters are deleted.
- `DataclassFieldAccess.is_config_type/is_container` owns configuration classification: meaning members being dataclasses must not make them configuration containers. Extraction, reconstruction, structural leaves, history, context and form selection use that owner. Code-editor updates use it and canonical raw reads; duplicate nested recursion and three replaced/dead helper paths are deleted.

### Source evidence

NRA `SourceModule`, `module_syntax_index`, `build_class_family_index`: 1,589 production/dependency modules, 9,923 class rows before/after, zero parse omissions. Evidence uses the producer, FormBridge, PyQt, OpenHCS, Toad, Core, current python-introspect and pycodify roots. Syntax/family evidence does not prove dynamic aliases, decorators, MRO or behavior.

Exact search after migration:

`rg -n 'raw_value_is_none|resolved_value_is_none'` across all five owned source and test roots: **0 hits**, exit1, stderr empty. Original two inspection properties, two DTO fields and four re-derivations are gone.

Evidence root: `/home/ts/.cache/agent-scratch/objectstate-declared-fields/`; `dto-members-{before,after}.json`, `dto-member-call-sites-before.json`, `dto-member-fixture-migrations.json`, `dto-null-flags-after.txt`.

### Confirmed behavior

Real Qt form/native typing, production Qt main-thread dispatcher, authenticated localhost ZMQ server/client, declaration-aware DTO decoding, mutation/catalog, reset, original-handle history undo, absence and view/server disposal pass. Explicit wire examples: `{"Value":{"value":null}}`, `{"Value":{"value":""}}`, `{"Value":{"value":"None"}}`, `{"Inherit":{}}`, `{"Unset":{}}`. Final journey also uses the existing metaclass-registry source required by OpenHCS. No provider or original saved input was used.

- 66 distinct producer cases pass: 64 in the first batch and two old source-generation assertions corrected and confirmed separately. Their former None-as-inheritance expectations contradicted the declared contract; strict literal-null and explicit-empty-config assertions replace them. Initial failure output retained.
- 43 focused FormBridge cases pass, including typed/compact member roundtrips, malformed-member rejection, code-editor updates and real ZMQ transport.
- 68 focused Qt cases pass.

Receipts: `dto-member-bridge-{journey,paired-final}.txt`, `dto-producer-tests-v1.txt`, `dto-codegen-correction.txt`, `dto-bridge-tests-v1.txt`, `dto-qt-tests-v1.txt`.

### Remaining application blocker

OpenHCS tests do not reach collection. The old installed metaclass-registry lacks `testing`; using the unchanged required source clears that import and exposes `TypeError: LazyNapariDisplayConfig.colormap must be str; got Inherit` during configuration startup. This wider lazy-validation cutover remains doctrine-owned under the existing unfinished field work. No skip, timeout increase, alternate test harness or installation was used. Receipts: `dto-openhcs-{tests-v1,paired-tests-v1}.txt`. The OpenHCS consumer source is pushed, not claimed fully application-verified.
