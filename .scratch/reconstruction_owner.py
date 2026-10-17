import ast,textwrap
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
root=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate')
p=root/'parameter_structure.py';s=p.read_text();s+='''
    def reconstruct(self, prefix, values, target, *, resolved=False):
        """Build one projection from its own payload, preserving scalar terminals.

        A container's stored None/Inherit/Unset is authoritative even when an
        editor retains child drafts. Nominal type comes from that payload, never
        from the declaration-owner index. Live and saved projections share this.
        """
        from objectstate.field_access import DataclassFieldAccess
        from objectstate.lazy_factory import get_base_type_for_lazy, replace_raw

        prototype = values[prefix] if prefix else target
        if prefix and not is_dataclass(prototype):
            return prototype
        prefix_dot = f"{prefix}." if prefix else ""
        direct = {}
        for path, value in values.items():
            if not path.startswith(prefix_dot):
                continue
            remainder = path[len(prefix_dot):]
            if "." in remainder:
                continue
            direct[remainder] = (
                self.reconstruct(path, values, target, resolved=resolved)
                if is_dataclass(value) else value
            )
        if not prefix:
            direct.update(self.excluded_values)
        if is_dataclass(prototype):
            if not resolved:
                return replace_raw(prototype, **direct)
            constructor = get_base_type_for_lazy(type(prototype)) or type(prototype)
            arguments = DataclassFieldAccess.raw_init_values(prototype, constructor)
            arguments.update(direct)
            return constructor(**arguments)
        return type(prototype)(**direct)
''';compile(s,str(p),'exec');p.write_text(s)
p=root/'object_state.py';s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);edits=[];deleted=[]
for _,n in idx.indexed_nodes_of_type(ast.FunctionDef):
 if n.name in {'_reconstruct_from_resolved','_reconstruct_from_parameter_snapshot','_reconstruct_from_prefix'}:
  start=min([n.lineno]+[d.lineno for d in n.decorator_list])-1;deleted.append((start,n.end_lineno));edits.append((start,n.end_lineno,''))
lines=s.splitlines(keepends=True)
for _,n in idx.indexed_nodes_of_type(ast.Call):
 if any(a<=n.lineno-1<b for a,b in deleted):continue
 if not isinstance(n.func,ast.Attribute):continue
 name=n.func.attr
 if name=='_reconstruct_from_resolved':
  prefix,values,target,structure=n.args
  call=ast.Call(func=ast.Attribute(value=structure,attr='reconstruct',ctx=ast.Load()),args=[prefix,values,target],keywords=[ast.keyword(arg='resolved',value=ast.Constant(value=True))])
 elif name in {'_reconstruct_from_parameter_snapshot','_reconstruct_from_prefix'}:
  values=n.args[1]if name.endswith('parameter_snapshot')else ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr='parameters',ctx=ast.Load())
  call=ast.Call(func=ast.Attribute(value=ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr='_parameter_structure',ctx=ast.Load()),attr='reconstruct',ctx=ast.Load()),args=[n.args[0],values,ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr='_extraction_target',ctx=ast.Load())],keywords=[])
 else:continue
 # Preserve the containing line's prefix/suffix. All observed calls are complete
 # expressions on their own logical line, including multiline calls.
 before=lines[n.lineno-1][:n.col_offset];after=lines[n.end_lineno-1][n.end_col_offset:]
 edits.append((n.lineno-1,n.end_lineno,before+ast.unparse(ast.fix_missing_locations(call))+after))
for a,b,text in sorted(edits,reverse=True):lines[a:b]=[text]
s=''.join(lines);compile(s,str(p),'exec');p.write_text(s)
