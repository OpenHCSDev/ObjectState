import ast,json
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
p=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/protocols/widget_adapters.py')
s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module)
selected=[n for _,n in idx.indexed_nodes_of_type(ast.ClassDef) if n.name in {'SpinBoxValueAdapter','SpinBoxAdapter','DoubleSpinBoxAdapter'}]
text='\n\n'.join(ast.get_source_segment(s,n) for n in selected)
out=Path('/home/ts/.cache/agent-scratch/objectstate-declared-fields/spinbox-members-after.txt');out.write_text(text+'\n')
print(json.dumps({'numeric_owners':[(n.name,n.lineno,[ast.unparse(b) for b in n.bases]) for n in selected],'numeric_none_decisions':[(n.lineno,ast.unparse(n)) for _,n in idx.indexed_nodes_of_type(ast.Compare) if any(c.lineno<=n.lineno<=c.end_lineno for c in selected) and any(isinstance(x,ast.Constant) and x.value is None for x in n.comparators)],'comparison_scope':'numeric classes, not unrelated nullable-text formatting or wire DTO projections'},indent=2))
