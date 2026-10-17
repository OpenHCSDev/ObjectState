import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
P=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/object_state.py');s=P.read_text();idx=module_syntax_index(SourceModule.from_source_path(P,s).parse().module);lines=s.splitlines(keepends=True)
n=next(n for _,n in idx.indexed_nodes_of_type(ast.FunctionDef)if n.name=='get_provenance')
old=''.join(lines[n.lineno-1:n.end_lineno]);body=old[old.index('        self._ensure_live_resolved()'):];body=body.replace('self._live_provenance.get(param_name)','self._live_provenance.get(field._path)')
new='''    def _read_provenance(self, field: FieldProxy):
        """Source of an inherited value; literal None never invents a source."""
'''+body
lines[n.lineno-1:n.end_lineno]=[new];s=''.join(lines)
s=s.replace('''    def inspect(self):
''','''    @property
    def provenance(self):
        self._require_present()
        return self._state._read_provenance(self)

    def inspect(self):
''');compile(s,str(P),'exec');P.write_text(s)
P=P.with_name('inspection.py');s=P.read_text().replace('match state.get_provenance(field_path):','match field.provenance:');P.write_text(s)
