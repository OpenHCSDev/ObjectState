## DTO correction checkpoint (not the completed node correction)

Removed the eleven Python-class-name DTO declarations. All six named DTO deletion checks pass; MIME metadata is retained. Missing and present previews are now members of the existing preview family and own rendering. The renderer no longer tests preview presence. Preview null/type flags are deleted too.

The declaration owner is not derivable from a raw/resolved datum (especially null or absence). `UiObjectStateFieldDeclaration` now owns its module/qualified symbol and import resolution for remote help; the detached string parser/importer is deleted. Scope/value type-name mirrors have no replacements.

Source-paired verification: **28 checks pass** (22 projection/codec cases and six declaration gates). The classifier gate remains failing and is explicitly excluded from this DTO-only result. The existing real Qt native-input → main-thread dispatch → authenticated localhost ZMQ → DTO decode → reset/history undo → disposal journey passes, including literal null, empty text and the string `None`. No provider, original saved input, build or shared installation was touched.

Initial failure evidence: `/home/ts/.cache/agent-scratch/objectstate-declared-fields/node-deletion-gates-before.txt` retains all eight expected deletion-check failures on the rejected heads. Current results: `node-dto-checks-v1.txt`, `node-dto-bridge-journey.txt`; constructor migration evidence: `node-dto-fixture-migrations.json` in the same evidence directory.

**Still unfinished:** operation-owning configuration/leaf values, removal of classifiers and the full application path. Normal OpenHCS startup still has the previously retained lazy `Inherit` validation failure; no application acceptance is claimed. Native Sending remains deferred and unchanged.
