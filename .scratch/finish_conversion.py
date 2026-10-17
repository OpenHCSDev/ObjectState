import ast,textwrap
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
p=Path('/home/ts/wt/formbridge-declared-fields/src/formbridge/forms/parameter_form_service.py');s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True)
n=next(n for _,n in idx.indexed_nodes_of_type(ast.FunctionDef)if n.name=='convert_value_to_type')
body=''.join(lines[n.lineno-1:n.end_lineno]).replace('def convert_value_to_type(', 'def _convert_domain_value(',1)
body=body.replace('''        # Handle string "None" literal
        if isinstance(value, str) and value == CONSTANTS.NONE_STRING_LITERAL:
            return None

''','')
body=body.replace('''            if value == CONSTANTS.EMPTY_STRING:
                return None''','''            if value == CONSTANTS.EMPTY_STRING:
                return Unset()''')
a=body.index('        # Handle empty strings in lazy context');b=body.index('        return value',a)
# The entire obsolete generic-empty/string-empty policy ends at the final return.
body=body[:a]+'        return value\n'
wrapper='''    def convert_value_to_type(
        self, value: ParameterValue, param_type: type, param_name: str, obj_type: type = None
    ) -> ParameterValue:
        """Convert domain input through its annotation; retain field directives."""
        return FieldValue.of(value).map(
            lambda raw: self._convert_domain_value(raw, param_type, param_name, obj_type)
        )

'''
lines[n.lineno-1:n.end_lineno]=[wrapper+body];s=''.join(lines)
# This module has no future import; put the state import after its docstring.
module=ast.parse(s);doc=module.body[0];end=doc.end_lineno if isinstance(doc,ast.Expr)and isinstance(doc.value,ast.Constant)and isinstance(doc.value.value,str)else 0
lines=s.splitlines(keepends=True);lines.insert(end,'from objectstate.field_value import FieldValue, Unset\n');s=''.join(lines);compile(s,str(p),'exec');p.write_text(s)
p=Path('/home/ts/wt/objectstate-declared-fields/src/objectstate/codegen.py');s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);n=next(n for _,n in idx.indexed_nodes_of_type(ast.FunctionDef)if n.name=='lazy_dataclass_carries_values');lines=s.splitlines(keepends=True);del lines[n.lineno-1:n.end_lineno];s=''.join(lines).replace('registers two formatters','registers the field formatters');compile(s,str(p),'exec');p.write_text(s)
