"""Complete the stored-value consumers; no compatibility surface remains."""
import ast,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'src/objectstate'
p=ROOT/'subfield_semantics.py';t=p.read_text()
t=t.replace('from objectstate.field_access import DataclassFieldAccess, DottedFieldPath','from objectstate.field_access import DataclassFieldAccess, DottedFieldPath\nfrom objectstate.field_value import FieldValue, Unset')
t=t.replace('''@dataclass(frozen=True, slots=True)
class MissingValue:
    """Nominal sentinel for an absent structural leaf."""


MISSING = MissingValue()


''','')
t=t.replace('raw_value is not MISSING','FieldValue.of(raw_value).has_value').replace('resolved_value is not MISSING','FieldValue.of(resolved_value).has_value').replace('saved_resolved_value is not MISSING','FieldValue.of(saved_resolved_value).has_value').replace('signature_default_value is not MISSING','FieldValue.of(signature_default_value).has_value')
# Longer names before suffixes: do not turn saved_resolved_value into saved_FieldValue.
t=t.replace('saved_FieldValue.of(resolved_value).has_value','FieldValue.of(saved_resolved_value).has_value')
t=t.replace('None if value_type is MISSING else type(value_type).__qualname__','type(value_type).__qualname__ if FieldValue.of(value_type).has_value else None')
t=t.replace('if value is MISSING:','if not FieldValue.of(value).has_value:')
t=t.replace('owner_inherited_value=raw_value is None and resolved_value is not None','owner_inherited_value=FieldValue.is_inherited(raw_value) and FieldValue.of(resolved_value).has_value')
t=re.sub(r'\bMISSING\b','Unset()',t)
p.write_text(t)
p=ROOT/'object_state.py';t=p.read_text().replace('    MISSING,\n','');t=re.sub(r'\bMISSING\b','Unset()',t);p.write_text(t)
p=ROOT/'__init__.py';t=p.read_text().replace('    MISSING,\n','').replace('    MissingValue,\n','').replace("    'MISSING',\n",'').replace("    'MissingValue',\n",'');p.write_text(t)
p=ROOT/'inspection.py';t=p.read_text();t='from objectstate.field_value import FieldValue, Unset\n'+t if 'from __future__'not in t else t.replace('from __future__ import annotations','from __future__ import annotations\nfrom objectstate.field_value import FieldValue, Unset')
t=t.replace('resolved_value = None\n        resolved_value_available = False','resolved_value = Unset()\n        resolved_value_available = False')
t=t.replace('return self.raw_value is None and self.resolved_value_available and (\n            self.resolved_value is not None\n        )','return FieldValue.is_inherited(self.raw_value) and self.resolved_value_available and FieldValue.of(self.resolved_value).has_value')
# Literal None remains literal None; inherited state is independently named.
needle='    @property\n    def raw_value_is_none(self) -> bool:'
t=t.replace(needle,'    @property\n    def raw_value_is_inherited(self) -> bool:\n        return FieldValue.is_inherited(self.raw_value)\n\n'+needle)
p.write_text(t)
p=ROOT/'resolution_sources.py';t=p.read_text().replace('FieldKey = tuple[type, str]','from objectstate.field_access import DataclassFieldAccess\nfrom objectstate.field_value import Unset\n\nFieldKey = tuple[type, str]')
t=t.replace('return object.__getattribute__(config, name)','return DataclassFieldAccess.raw_value(config, name)').replace('''    if config is None:
        return None
    try:
        return DataclassFieldAccess.raw_value(config, name)
    except AttributeError:
        return None''','''    if config is None:
        return Unset()
    try:
        return DataclassFieldAccess.raw_value(config, name)
    except AttributeError:
        return Unset()''');p.write_text(t)
p=ROOT/'codegen.py';t=p.read_text().replace('from objectstate.field_access import DataclassFieldAccess','from objectstate.field_access import DataclassFieldAccess\nfrom objectstate.field_value import FieldValue')
t=t.replace('DataclassFieldAccess.raw_value(value, field.name) is not None','FieldValue.of(DataclassFieldAccess.raw_value(value, field.name)).has_value')
t=t.replace('if current is None:\n            return False','if FieldValue.is_inherited(current):\n            return False')
t+='''\n\nclass FieldValueFormatter(SourceFormatter):
    """Field states render their declared constructor, never a None stand-in."""
    priority = 38
    formats = FieldValue

    def can_format(self, value: object) -> bool:
        return isinstance(value, self.formats)

    def format(self, value: FieldValue, context: FormatContext) -> SourceFragment:
        return value.source(context)
''';p.write_text(t)
for p in ROOT.glob('*.py'):ast.parse(p.read_text(),filename=str(p))
