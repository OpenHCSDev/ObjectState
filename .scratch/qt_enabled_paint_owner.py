"""Enabled paint derives from admitted state, never checkbox paint or None policy."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
ROOT=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive')
p=ROOT/'services/enabled_field_styling_service.py';s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
methods={
'apply_initial_enabled_styling':'''    @staticmethod
    def _enabled_field(manager):
        return next((field for field in manager.fields.children if Enableable.is_parameter_key(field.name)), None)

    def apply_initial_enabled_styling(self, manager) -> None:
        """Paint this materialized scope from its canonical effective value."""
        if self._should_skip_optional_dataclass_styling(manager, "INITIAL ENABLED STYLING"):
            return
        self._last_enabled_values.pop(manager, None)
        field = self._enabled_field(manager)
        if field is not None:
            self._paint_enabled_scope(manager, field)
''',
'refresh_enabled_styling':'''    def refresh_enabled_styling(self, manager) -> None:
        """Own the single enabled-paint traversal for this form subtree."""
        if self._should_skip_optional_dataclass_styling(manager, "REFRESH ENABLED STYLING"):
            return
        field = self._enabled_field(manager)
        if field is not None:
            self._paint_enabled_scope(manager, field)
        for nested_manager in manager.nested_managers.values():
            self.refresh_enabled_styling(nested_manager)
''',
'on_enabled_field_changed':'''    def on_enabled_field_changed(self, manager, field: FieldProxy) -> None:
        """A changed enable declaration invalidates its scope and descendants."""
        if Enableable.is_parameter_key(field.name):
            self.refresh_enabled_styling(manager)

    @staticmethod
    def _is_enabled(field: FieldProxy) -> bool:
        value = field.value
        return FieldValue.of(value).has_value and bool(value)

    def _paint_enabled_scope(self, manager, field: FieldProxy) -> None:
        effective = self._is_enabled(field) and not self._is_any_ancestor_disabled(manager)
        if manager in self._last_enabled_values and self._last_enabled_values[manager] == effective:
            return
        self._last_enabled_values[manager] = effective
        direct_widgets = self._get_direct_widgets(manager)
        if manager.form_tree.owning_groupbox(manager) is not None:
            self._apply_nested_config_styling(manager, effective)
        else:
            self._apply_top_level_styling(manager, effective, direct_widgets)
''',
'_is_any_ancestor_disabled':'''    def _is_any_ancestor_disabled(self, manager) -> bool:
        current = manager._parent_manager
        while current is not None:
            field = self._enabled_field(current)
            if field is not None and not self._is_enabled(field):
                return True
            current = current._parent_manager
        return False
''',
'_apply_top_level_styling':'''    def _apply_top_level_styling(self, manager, resolved_value: bool, direct_widgets: list) -> None:
        """Paint only this scope; refresh_enabled_styling owns descendant work."""
        self._set_widgets_dimmed(direct_widgets, not resolved_value, skip_labels=not resolved_value)
'''}
for _,n in idx.indexed_nodes_of_type(ast.FunctionDef):
 if n.name in methods:
  a=min([n.lineno]+[d.lineno for d in n.decorator_list])-1;edits.append((a,n.end_lineno,methods[n.name]))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t+'\n']
s=''.join(lines).replace('from objectstate import DottedFieldPath','from objectstate import FieldProxy, FieldValue\nfrom python_introspect import Enableable')
s=s.replace('''        # Check if ANY ancestor has enabled=False
        ancestor_is_disabled = self._is_any_ancestor_disabled(manager)
        logger.debug(f"[ENABLED HANDLER] field_id={manager.field_id}, ancestor_is_disabled={ancestor_is_disabled}")

        should_dim = ancestor_is_disabled or not resolved_value''','''        should_dim = not resolved_value''')
compile(s,str(p),'exec');p.write_text(s)
# Delete forwarding-only enabled stages: the existing paint owner does the work.
p=ROOT/'services/field_change_dispatcher.py';s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True)
for _,n in idx.indexed_nodes_of_type(ast.ClassDef):
 if n.name=='EnabledFieldStyleStage':lines[n.lineno-1:n.end_lineno]=[]
s=''.join(lines).replace('        self._enabled_field_style = EnabledFieldStyleStage()\n','').replace('            self._enabled_field_style.run(context)','            source._enabled_field_styling_service.on_enabled_field_changed(source, event.field)')
compile(s,str(p),'exec');p.write_text(s)
for relative,method in [('forms/parameter_form_manager.py','sync_enabled_field_visuals'),('forms/parameter_form_chrome_sync.py','enabled_field_visuals')]:
 p=ROOT/relative;s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True)
 for _,n in idx.indexed_nodes_of_type(ast.FunctionDef):
  if n.name==method:lines[n.lineno-1:n.end_lineno]=[]
 s=''.join(lines);compile(s,str(p),'exec');p.write_text(s)
