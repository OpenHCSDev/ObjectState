## Inspection/member correction delivered (not completion of the entire cutover)

Pair: ObjectState `9faba28`, FormBridge `37a0556`, PyQt `02db991`.

- `FieldInspection` declares exactly one effective value: `resolved: FieldValue`. The parallel `resolved_value`, availability flag and broad exception fallback are deleted. Original resolver exception identity propagates.
- Five original inspection/projection consumer methods migrated: null classification, inherited classification, type projection, JSON projection and preview projection. Inheritance relation is owned by the member and shared with structural-owner projection. Thirty additional AST-selected flag uses now invoke member behavior across resolver, structural projection, construction and Qt services.
- FieldValue has no `inherited`, `has_value` or `is_none` class flags. `project` has no absence default: it passes the real directive or datum through existing polymorphic resolution to the view. Bridge absence is a visible `Unset` preview/member spelling, not fabricated null. Public DTO wire `resolved_value` and its wire null-description fields remain unchanged; their similarly named reads are not FieldInspection aliases.
- `SpinBoxValueAdapter` owns integer/double rendering, placeholder/range behavior and native admission. Leaves retain numeric type/range and floating formatting only. None renders as literal `None`; directives render their preview; real minima are data. No numeric `value is None`/`value is not None` branch or magic one-space remains in the AST-selected numeric class family (scoped rg: zero).
- Native signal declarations include their actual receiver. Qt emits textEdited before updating its number, so unchanged-number text admission is separate from valueChanged; no sender() guess or duplicated publication. Input tracking begins at control construction. Retiring special paint does not repeatedly repaint partial input and erase a minus sign.

### Source evidence

NRA ModuleSyntaxIndex/class-family census covers eight production/dependency roots: 1,585 modules; 9,875 before/9,876 after class rows; zero parse errors. Conditional Qt declarations/runtime signal bindings are not claimed statically resolved. Actual C3 MRO and shared implementation identity were checked for base/no-scroll int/double controls. A new numeric leaf supplies its native Qt base, type/range and any real formatter; it does not copy data-state or subscription algorithms.

Requested raw rg `is_none|has_value|\\.inherited\\b`: **156 -> 115** across the same corpus. Remaining matches are wire DTO/null-description names, unrelated source fields and logging; FieldValue flag declarations/reads are gone. `resolved_value_available` production hits: **0**. Five inspection consumers are not counted as thirty separate callers; the latter number is AST-selected expression sites.

Owned evidence: `/home/ts/.cache/agent-scratch/objectstate-declared-fields/inspection-spinbox-{before,after}.json`, `meaning-flags-{before,after}.txt`, `meaning-member-migrations.json`, `inspection-spinbox-owners-after.json`, `spinbox-runtime-mro.txt` and `spinbox-members-after.txt`. Transformations remain under the persistent producer checkout `.scratch/`. The first signal tuple selection also selected the outer tuple; that unsupported site was corrected before acceptance, not claimed as semantic proof from parsing.

### Confirmed behavior

- **30 producer tests passed**: existing handles plus inspection/scopeless resolution; literal null/absence/inheritance, exact read failure, dirty/provenance and source rules retained.
- **68 real Qt cases passed**: localized float roundtrips, literal/wrapped null and directives, exact minima, one native zero admission, unchanged numeric minimum, range/signal-block restoration, default form, existing/nested refresh and reset.
- **5 bridge projection cases passed**: absent member versus null and literal strings.
- Real source-paired Qt control journey and real bridge mutation/catalog/history journey passed, including original-handle undo.

Earlier import, signal-ordering, tuple-selection, constructor-tracking and negative-entry failures are retained separately; acceptance is the corrected run, not a silent retry. Test expectation that None means inherited display was replaced by explicit Inherit plus a distinct literal-null assertion; no skip/xfail, weakened count, timeout increase or provider replay.

This is source-paired acceptance, not shared installation or full OpenHCS/Core/Qt-window cutover. Existing drafts and saved-data migration remain unfinished.
