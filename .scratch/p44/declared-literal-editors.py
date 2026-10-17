import ast
from pathlib import Path
p=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive/forms/widget_strategies.py');s=p.read_text();tree=ast.parse(s);lines=s.splitlines(keepends=True)
container='''class TypedLiteralContainerEdit(
    FieldTextValueMixin, PlaceholderStateMixin, QLineEdit, ValueGettable,
    ValueSettable, ChangeSignalEmitter, CurrentValueValidatable,
    metaclass=PyQtWidgetMeta,
):
    """Literal text paints and parses through its bound field declaration."""

    def __init__(self, declaration: ValueDeclaration, param_name="", parent=None):
        self._declaration = declaration
        self._param_name = param_name
        super().__init__(parent)
        self.setValidator(TypedLiteralValidator(self._parse_text, self))
        self.setToolTip(
            f"Enter a Python {declaration.literal_name} literal, "
            f"for example {declaration.literal_example}."
        )

    def set_value(self, value):
        def paint(raw):
            if raw is None:
                return None
            raw = self._declaration.normalize_data(raw)
            self._declaration.require_literal(raw)
            return self._declaration.project_literal(raw)
        super().set_value(FieldValue.of(value).map(paint))

    def _read_concrete_value(self):
        return self._parse_current_text()

    def validate_current_value(self):
        self.get_value()

    def connect_change_signal(self, callback):
        self.connect_debounced_text_signal(
            callback, self._parse_current_text,
            is_committable=self._current_text_is_committable,
        )

    def _current_text_is_committable(self):
        try:
            self._parse_current_text()
        except ValueError:
            return False
        return True

    def _parse_current_text(self):
        return self._parse_text(self.text())

    def _parse_text(self, text):
        text = text.strip()
        if text == "":
            return None
        value = parse_literal_container(text, self._declaration)
        return ParameterFormService().convert_value_to_type(
            value, self._declaration.annotation, self._param_name,
        )
'''
parser='''def parse_literal_container(text: str, declaration: ValueDeclaration) -> ParameterValue:
    """Parse external literal syntax; the declaration validates its shape."""
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError) as exc:
        raise LiteralContainerSyntaxError(
            f"Expected a valid {declaration.literal_name} literal, got {text!r}."
        ) from exc
    try:
        return declaration.require_literal(value)
    except ValueError as exc:
        raise LiteralContainerKindError(str(exc)) from exc
'''
factory='''class LiteralWidgetFactory:
    """Construct controls selected by the existing declaration family."""

    def create(self, request):
        return ValueDeclaration.of(request.source.param_type).literal_editor(self, request)

    def container_editor(self, request):
        widget = TypedLiteralContainerEdit(
            ValueDeclaration.of(request.source.param_type), request.source.param_name,
        )
        widget.set_value(request.current_value)
        return widget

    def union_editor(self, request):
        widget = TypedLiteralUnionEdit(request.source.param_name, request.source.param_type)
        widget.set_value(request.current_value)
        return widget


LITERAL_WIDGET_FACTORY = LiteralWidgetFactory()
'''
edits=[]
for n in tree.body:
 if isinstance(n,ast.ClassDef) and n.name=='TypedLiteralContainerEdit':edits.append((n.lineno-1,n.end_lineno,container))
 if isinstance(n,ast.FunctionDef) and n.name=='parse_literal_container':edits.append((n.lineno-1,n.end_lineno,parser))
 if isinstance(n,ast.FunctionDef) and n.name=='project_literal_edit_value':edits.append((n.lineno-1,n.end_lineno,''))
first=next(n.lineno-1 for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LiteralContainerWidgetFactory')
last=next(n.end_lineno for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(x,ast.Name) and x.id=='LITERAL_UNION_WIDGET_FACTORY' for x in n.targets))
edits.append((first,last,factory))
for start,end,new in sorted(edits,reverse=True):lines[start:end]=[new+'\n']
s=''.join(lines)
s=s.replace('from objectstate.field_value import ', 'from objectstate.declarations import ValueDeclaration\nfrom formbridge.forms.parameter_form_service import ParameterFormService\nfrom objectstate.field_value import ',1)
s=s.replace('        self._param_type = param_type\n        members = get_args(param_type)\n        self._accepts_none = type(None) in members\n        self._accepts_plain_string = str in members','        self._declaration = ValueDeclaration.of(param_type)\n        members = get_args(param_type)')
s=s.replace('self._accepts_plain_string','self._declaration.accepts_data("")').replace('self._accepts_none','self._declaration.accepts_data(None)').replace('self._param_type','self._declaration.annotation')
s=s.replace('        projected = project_literal_edit_value(value)\n        super().set_value(projected)','        projected = FieldValue.of(value).map(\n            lambda raw: None if raw is None else self._declaration.project_literal(raw)\n        )\n        super().set_value(projected)')
s=s.replace('        from formbridge.forms.parameter_form_service import ParameterFormService\n\n','')
old='''        literal_container_widget = LITERAL_CONTAINER_WIDGET_FACTORY.create(resolved)
        if literal_container_widget is not None:
            return literal_container_widget

        literal_union_widget = LITERAL_UNION_WIDGET_FACTORY.create(resolved)
        if literal_union_widget is not None:
            return literal_union_widget'''
assert old in s
s=s.replace(old,'''        literal_widget = LITERAL_WIDGET_FACTORY.create(resolved)
        if literal_widget is not None:
            return literal_widget''')
ast.parse(s);p.write_text(s)
