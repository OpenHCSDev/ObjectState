## Declaration-owned checkpoint (source-paired, not installed)

Pushed heads: ObjectState 93eae56; FormBridge b5d3af8; PyQt 8690060; OpenHCS f0c07c411. Dependency python-introspect ffcffaa (PR #25).

ValueDeclaration compiles annotations once. ParameterOwnerDeclaration owns parameters, field_types and init_field_names (one definition each); constructor and configuration owners share that implementation. FieldValue.of only preserves meaning members or boxes data; it does not classify runtime payloads. Named configuration access is absent on scalar leaves. Declared collection element types own traversal and serialization. DeclaredValue shares metadata/copy/serialization lifecycle between configuration and collection values.

InheritedDefault is the single frozen class-keyed default record; ValueDefault/FactoryDefault materialize it. own_default and inherited_default now index declared fields and raise KeyError for unknown names. Their direct resolver callers validate against the requested declaration; configuration_mro(field_name) filters ancestors by their declared fields before reading defaults. All touched production roots have zero `_inherited_default`, `_resolve_type` and `__objectstate_rebuild__` references. UIParameterVisibilityPolicy owns field visibility metadata, keyed by the existing policy class. CompactFieldProjection is also its own metadata key; no string-key compatibility reader remains.

Text-line counts (published baseline -> checkpoint):

| production root | is_container | is_config_type | literal `| None` | getattr | get_base_type_for_lazy |
| --- | --- | --- | --- | --- | --- |
| ObjectState 1479884 | 27 -> 0 | 2 -> 0 | 94 -> 91 | 37 -> 16 | 46 -> 2 |
| FormBridge bdafb52 | 3 -> 0 | 6 -> 0 | 480 -> 468 | 18 -> 16 | 8 -> 0 |

The two remaining lazy callback-name lines are its definition and register_type_resolver registration; zero callers, imports or exports remain in the touched production family. The normalization wrapper/cache and per-caller fallback expressions are removed. Archived dirty-before normalization count was 45, now 2.

FormBridge FieldValue.of: published 3 -> 2; archived dirty-before 15 -> 2. get_base_type_for_lazy: 8 -> 0. metadata.get: 4 -> 2. Combined requested regex: published 15 -> 4; archived dirty-before 27 -> 4. The remaining FieldValue.of sites preserve DTO meaning after mapping JSON data, not payload kind. The remaining metadata.get sites read canonical runtime code-document tokens, not declaration metadata.

widget_creation_type consumers: WidgetCreationPipeline.__init__ selected an enum by the string; it now calls param_info.creation_type(WidgetCreationType). ParameterFormManager._create_parameter_widget only logged it; it now logs the actual info class. All four string ClassVars are deleted.

NRA syntax/family evidence: 1,590 production/dependency modules, 9,953 classes, no parse errors. AST calls: ObjectState getattr 28 -> 13, FormBridge 17 -> 15; is_container/is_config_type calls zero, is_dataclass exactly one annotation compiler call. Dynamic resolution is not established by these syntax counts; the actual source-paired journey below checks the affected behavior.

Exact deleted Python type-name DTO declarations remain: source_type (1), object_state_path_type (2), raw_value_type (2), resolved_value_type (2), object_type (3), help_target_type (1). Genuine mime_type is retained. Deletion gates cover the exact declarations, not all *_type fields.

Verification: python-introspect public resolver/analyzer 64 passed; producer declaration/handle/inspection/scopeless/codegen/deletion cases 51 passed; bridge DTO/deletion cases 29 passed; Qt declared/numeric cases 66 passed. Actual source-paired native Qt input, main-thread dispatch, authenticated localhost ZMQ, DTO decode, reset, undo and disposal passed with null, empty string, text None, inheritance and absence. No provider and no installation.

Still unfinished: OpenHCS config startup reaches SourceBindingsConfig.__post_init__ but attempts to iterate Inherit in its source-binding normalization. Earlier removed has_value reads in the shared normalization owner are repaired; the whole remaining post-init normalizer needs a directive-aware owner pass. The old test_subfield_semantics.py still imports deleted MISSING/string APIs and fails collection; this failure is retained, not skipped or xfailed. Full OpenHCS/app acceptance and #32/#46 cutover are not complete. doctrine-segment remains the implementation owner.

Dependency: python-introspect ffcffaa, draft PR #25. No shared runtime publication/restart performed.
