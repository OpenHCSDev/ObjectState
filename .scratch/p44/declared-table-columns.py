import ast
from pathlib import Path
p=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/widgets/editable_table.py');s=p.read_text();tree=ast.parse(s);lines=s.splitlines(keepends=True);edits=[]
for n in ast.walk(tree):
 if isinstance(n,ast.FunctionDef) and n.name=='_collect':
  new='''    @classmethod
    def _collect(cls, row_type, prefix, columns):
        declaration = ValueDeclaration.of(row_type)
        hints = declaration.annotations
        for row_field in declaration.declared_fields():
            annotation, metadata = cls._split_annotated(hints[row_field.name])
            ValueDeclaration.of(annotation).choose_declaration(
                cls, row_type=row_type, row_field=row_field,
                path=(*prefix, row_field.name), columns=columns,
                annotation=(hints[row_field.name] if any(isinstance(item, AnnotationChoices) for item in metadata) else annotation),
            )

    @classmethod
    def config_declaration(cls, declared_type, *, path, columns, **arguments):
        cls._collect(declared_type, path, columns)

    @classmethod
    def nullable_declaration(cls, inner, **arguments):
        cls.scalar_declaration(inner.annotation, **arguments)

    @classmethod
    def scalar_declaration(cls, declared_type, *, row_type, row_field, path, columns, annotation):
        editor = CellEditor.for_annotation(annotation)
        if editor is None:
            return
        hints = ValueDeclaration.of(row_type).annotations
        columns.append(DataclassFieldColumn(
            index=len(columns), path=path, declaring_type=row_type, editor=editor,
            label=declared_field_label(hints[row_field.name]) or row_field.name.replace('_', ' ').title(),
            tooltip=SignatureAnalyzer.extract_field_documentation(row_type, row_field.name),
        ))
'''
  edits.append((min(n.lineno,*[d.lineno for d in n.decorator_list])-1,n.end_lineno,new))
for a,b,new in sorted(edits,reverse=True):lines[a:b]=[new+'\n']
s=''.join(lines)
s=s.replace('from objectstate import ObjectStateSubfieldSemanticIndex, StructuralValuePath','from objectstate import ObjectStateSubfieldSemanticIndex, StructuralValuePath\nfrom objectstate.declarations import ValueDeclaration')
s=s.replace('    default: object = MISSING\n','')
s=s.replace('''        for editor_type in cls.__registry__.values():
            if editor_type.accepts(annotation):
                return editor_type(annotation)''','''        declaration = ValueDeclaration.of(annotation)
        for editor_type in cls.__registry__.values():
            editor = editor_type.select(declaration, annotation)
            if editor is not None:
                return editor''')
s=s.replace('''    def accepts(cls, annotation: object) -> bool: ...''','''    def select(cls, declaration, annotation): ...''',1)
s=s.replace('''class ScalarTextCellEditor(CellEditor):''','''class AnnotationCellEditor(CellEditor):
    @classmethod
    def select(cls, declaration, annotation):
        return cls(annotation) if cls.accepts(annotation) else None

    @classmethod
    @abstractmethod
    def accepts(cls, annotation): ...


class ScalarTextCellEditor(AnnotationCellEditor):''')
s=s.replace('class BooleanCellEditor(CellEditor):','class BooleanCellEditor(AnnotationCellEditor):').replace('class ChoiceCellEditor(CellEditor):','class ChoiceCellEditor(AnnotationCellEditor):')
old='''    @classmethod
    def accepts(cls, annotation: object) -> bool:
        if get_origin(annotation) is not tuple:
            return False
        arguments = get_args(annotation)
        return (
            len(arguments) == 2
            and arguments[1] is Ellipsis
            and isinstance(arguments[0], type)
            and is_dataclass(arguments[0])
        )'''
assert old in s
s=s.replace(old,'''    @classmethod
    def select(cls, declaration, annotation):
        return declaration.collection_cell_editor(cls)''')
s=s.replace('RecordTupleCellEditor','RecordSequenceCellEditor')
s=s.replace('''        self.annotation = annotation''','''        self.annotation = annotation
        self.declaration = ValueDeclaration.of(annotation)''',1)
s=s.replace('return get_args(self.annotation)[0]','return self.declaration.item.require_config_type()')
s=s.replace('return tuple(cast(tuple, value))','return self.declaration.normalize_data(value)').replace('return tuple(cast(tuple, raw))','return self.declaration.normalize_data(raw)')
# The empty selection is rebuilt in the field's declared container, not assumed tuple.
start=s.index('class RecordSequenceCellEditor(');end=s.index('@dataclass',start)
part=s[start:end].replace('return ()','return self.declaration.normalize_data(())')
s=s[:start]+part+s[end:]
s=s.replace('''    def draft_raw(self, values: Mapping[str, object]) -> tuple[object, ...]:
        """Raw cells for a new row: given values, then field defaults, then empty."""

        return tuple(
            column.editor.raw_for(values[column.name])
            if column.name in values
            else (
                column.editor.raw_for(column.default)
                if column.default is not MISSING
                else column.editor.empty_raw()
            )
            for column in self.columns
        )''','''    def draft_raw(self, values: Mapping[str, object]) -> tuple[object, ...]:
        """Each column materializes its declaration's default for this new row."""
        return tuple(column.draft_raw(values) for column in self.columns)''')
anchor='''    def read_only(self) -> ColumnDef:'''
assert anchor in s
s=s.replace(anchor,'''    def draft_raw(self, values):
        if self.name in values:
            return self.editor.raw_for(values[self.name])
        return ValueDeclaration.of(self.declaring_type).own_default(self.name).fold(
            self.editor.raw_for, lambda directive: self.editor.empty_raw(),
        )

'''+anchor)
s=s.replace('len(fields(self.row_type))','len(ValueDeclaration.of(self.row_type).declared_fields())')
s=s.replace('return self.row_type(**{column.name: value for column, value in zip(self.columns, values)})','return ValueDeclaration.of(self.row_type).construct({column.name: value for column, value in zip(self.columns, values)})')
s=s.replace('from dataclasses import MISSING, dataclass, field, fields, is_dataclass, replace','from dataclasses import dataclass, field, replace')
ast.parse(s);p.write_text(s)
