from pathlib import Path
P=Path('/home/ts/wt/toad-declared-fields/src/toad/forms/editors.py');s=P.read_text().replace('from formbridge.forms.ui_utils import format_enum_display','from formbridge.forms.ui_utils import format_enum_display\nfrom objectstate import FieldValue')
s=s.replace('''    def value_text(self, value: object) -> str:
        """How a value of this field reads."""
        return self.field.placeholder if value is None else str(value)
''','''    def value_text(self, value: object) -> str:
        """A native entry projects absence without turning it into input data."""
        return self.field.placeholder if value is None or not FieldValue.of(value).has_value else str(value)

    def read_value(self) -> object:
        raise NotImplementedError

    def commit(self) -> None:
        """An explicit commit reads this control, not a manufactured type default."""
        try:
            value = self.read_value()
        except (TypeError, ValueError) as error:
            self.refuse(error)
        else:
            self.send(value)
''')
s=s.replace('''        super().__init__(value=bool(field.value))''','''        value = field.value
        super().__init__(value=bool(FieldValue.of(value).has_value and value))''')
s=s.replace('''    def paint(self) -> None:
        with self.prevent(Checkbox.Changed):
            self.value = bool(self.field.value)
''','''    def read_value(self) -> object:
        return self.value

    def paint(self) -> None:
        value = self.field.value
        with self.prevent(Checkbox.Changed):
            self.value = bool(FieldValue.of(value).has_value and value)
        self.tooltip = None if FieldValue.of(value).has_value else repr(value)
''')
a=s.index('        try:\n            value = self.read(self.value)',s.index('class LineEditor'));b=s.index('    def paint(self)',a)
s=s[:a]+'''        self.commit()

    def read_value(self) -> object:
        return self.read(self.value)

'''+s[b:]
s=s.replace('super().__init__(str(field.value or ""))','super().__init__(self.value_text(field.value))').replace('value = str(self.field.value or "")','value = self.value_text(self.field.value)')
s=s.replace('''        self.send(self.text)

    def paint(self)''','''        self.send(self.text)

    def read_value(self) -> object:
        return self.text

    def paint(self)''')
s=s.replace('''    def options(self) -> Iterable[tuple[str, object]]:
        """Each value on offer, with how it reads."""''','''    def read_value(self) -> object:
        if self.value is Select.NULL:
            raise ValueError("Choose a value before committing this field")
        return self.value

    def options(self) -> Iterable[tuple[str, object]]:
        """Each value on offer, with how it reads."""''')
s=s.replace('''    """A field that may hold nothing: a box says whether it holds a value, and the
    editor of that value is shown while it does."""''','''    """A nullable field; controls edit data and the box projects non-nullness.

    Keep the member editable while null so a numeric value can be entered before
    committing it. Enabling never leaves a checked box over backend None.
    """''')
s=s.replace('''        self.holds_value = Checkbox("Set", value=field.value is not None)
        self.member = ValueEditor.declared_for(field.member)
        self.member.display = field.value is not None''','''        value = field.value
        self.holds_value = Checkbox("Not None", value=FieldValue.of(value).has_value and value is not None)
        self.member = ValueEditor.declared_for(field.member)''')
s=s.replace('''        self.member.display = message.value
        if not message.value:
            self.send(None)
''','''        if message.value:
            self.member.commit()
        else:
            self.send(None)
        self.paint()
''')
s=s.replace('''        return "not set" if value is None else self.member.value_text(value)''','''        return "None" if value is None else self.member.value_text(value)''')
s=s.replace('''        held = self.field.value is not None
        with self.prevent(Checkbox.Changed):
            self.holds_value.value = held
        self.member.display = held
        self.member.paint()''','''        value = self.field.value
        held = FieldValue.of(value).has_value and value is not None
        with self.prevent(Checkbox.Changed):
            self.holds_value.value = held
        self.holds_value.tooltip = None if FieldValue.of(value).has_value else repr(value)
        self.member.paint()

    def read_value(self) -> object:
        return self.member.read_value() if self.holds_value.value else None''')
compile(s,str(P),'exec');P.write_text(s)
