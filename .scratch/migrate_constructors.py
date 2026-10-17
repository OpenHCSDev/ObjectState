"""Delete obsolete constructor patch scopes across their complete consumer family."""
import ast,textwrap
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
ROOTS=[Path('/home/ts/wt/formbridge-declared-fields/src'),Path('/home/ts/wt/pyqt-declared-fields/src'),Path('/home/ts/wt/openhcs-declared-fields/openhcs'),Path('/home/ts/wt/toad-declared-fields/src')]
for root in ROOTS:
 for path in root.rglob('*.py'):
  source=path.read_text()
  if 'patch_lazy_constructors'not in source and 'inherit_as_none'not in source:continue
  source=source.replace('inherit_as_none','inherit_fields')
  # Process innermost scopes first. NRA retains original source positions.
  while True:
   parsed=SourceModule.from_source_path(path,source).parse();syntax=module_syntax_index(parsed.module)
   matches=[n for _,n in syntax.indexed_nodes_of_type(ast.With) if any('patch_lazy_constructors'in ast.unparse(i.context_expr) for i in n.items)]
   if not matches:break
   node=max(matches,key=lambda n:n.lineno);lines=source.splitlines(keepends=True)
   assert len(node.items)==1,(path,node.lineno,'multi-context scope requires semantic review')
   body=''.join(lines[node.body[0].lineno-1:node.end_lineno]);body=textwrap.dedent(body)
   replacement=textwrap.indent(body,' '*node.col_offset)
   source=''.join(lines[:node.lineno-1])+replacement+''.join(lines[node.end_lineno:])
  parsed=SourceModule.from_source_path(path,source).parse();syntax=module_syntax_index(parsed.module);edits=[]
  for _,node in syntax.indexed_nodes_of_type(ast.ImportFrom):
   if any(n.name=='patch_lazy_constructors' for n in node.names):
    names=[n for n in node.names if n.name!='patch_lazy_constructors']
    replacement=ast.unparse(ast.ImportFrom(module=node.module,names=names,level=node.level))if names else''
    edits.append((node.lineno-1,node.end_lineno,' '*node.col_offset+replacement+'\n'))
  for _,node in syntax.indexed_nodes_of_type(ast.FunctionDef):
   if node.name=='_patch_lazy_constructors':edits.append((min([node.lineno]+[d.lineno for d in node.decorator_list])-1,node.end_lineno,''))
  for _,node in syntax.indexed_nodes_of_type(ast.AnnAssign):
   if isinstance(node.target,ast.Name)and node.target.id=='patch_lazy_constructors':edits.append((node.lineno-1,node.end_lineno,''))
  lines=source.splitlines(keepends=True)
  for start,end,replacement in sorted(edits,reverse=True):lines[start:end]=[replacement]
  source=''.join(lines)
  # Constructor keywords are whole, line-owned dependencies at the witnessed sites.
  lines=source.splitlines(keepends=True)
  lines=[line for line in lines if 'patch_lazy_constructors=patch_lazy_constructors'not in line]
  source=''.join(lines)
  ast.parse(source,filename=str(path));path.write_text(source);print(path)
