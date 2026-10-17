import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
ROOT=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive')
p=ROOT/'services/widget_service.py';s=p.read_text();s=s.replace('''        if value is None:
            self.show_resolved_value_as_placeholder(widget, param_name, manager)
        elif value is not None:
            if self.widget_enhancer.has_placeholder_state(widget):
                logger.debug("Clearing placeholder state for concrete value")
                self.widget_enhancer._clear_placeholder_state(widget)
''','') # Original source is already migrated; replace that owned block instead.
old='''        if FieldValue.of(value).inherited:
            self.show_resolved_value_as_placeholder(widget, param_name, manager)
        else:
            if self.widget_enhancer.has_placeholder_state(widget):
                logger.debug("Clearing placeholder state for concrete value")
                self.widget_enhancer._clear_placeholder_state(widget)
''';assert old in s;s=s.replace(old,'        self.show_resolved_value_as_placeholder(widget, param_name, manager)\n')
old='''        full_path = f"{manager.field_id}.{param_name}" if manager.field_id else param_name
        resolved_value = manager.state.get_resolved_value(full_path)''';new='''        full_path = f"{manager.field_id}.{param_name}" if manager.field_id else param_name
        raw_value = manager.state.parameters[full_path]
        if not FieldValue.of(raw_value).inherited:
            if self.widget_enhancer.has_placeholder_state(widget):
                self._dispatch_widget_update(widget, raw_value)
            return False
        resolved_value = manager.state.get_resolved_value(full_path)''';assert old in s;s=s.replace(old,new);compile(s,str(p),'exec');p.write_text(s)
p=ROOT/'services/parameter_ops_service.py';s=p.read_text();s=s.replace('''        if FieldValue.of(reset_value).inherited:
            self.refresh_single_placeholder(manager, param_name)
''','')
a=s.index('        # Only refresh if value is None (needs placeholder)');b=s.index('        if manager._widget_service.show_resolved_value_as_placeholder',a);s=s[:a]+s[b:]
a=s.index('                full_path = f"{manager.field_id}.{param_name}"');s=s[:a]+'''                with monitor.measure():
                    manager._widget_service.show_resolved_value_as_placeholder(
                        widget, param_name, manager
                    )
'''+s[s.index('\n',s.index('                    PyQt6WidgetEnhancer._clear_placeholder_state(widget)',a))+1:]
s=s.replace('from objectstate.field_value import FieldValue\n','');compile(s,str(p),'exec');p.write_text(s)
p=ROOT/'services/field_change_dispatcher.py';s=p.read_text();a=s.index('        # FIX: Check current value instead of _user_set_fields.');b=s.index('        if DEBUG_DISPATCHER:\n            logger.info(f"      ✅ Refreshing placeholder',a);s=s[:a]+s[b:];s=s.replace('from objectstate import FieldValue\n','');compile(s,str(p),'exec');p.write_text(s)
