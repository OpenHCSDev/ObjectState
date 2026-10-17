"""One admitted field and one operation per UI mutation; delete reset copies."""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
ROOT=Path('/home/ts/wt/pyqt-declared-fields/src/pyqt_reactive')
p=ROOT/'services/field_change_dispatcher.py';s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
bodies={
'FieldChangeEvent':'''@dataclass(frozen=True)
class FieldChangeEvent(ABC):
    """An admitted field and its UI source; each operation owns its mutation."""
    field: FieldProxy
    source_manager: "ParameterFormManager"
    is_reset: ClassVar[bool] = False

    def __post_init__(self):
        if self.field.state is not self.source_manager.state:
            raise FieldAccessError("The field belongs to a different editing state")

    @property
    def field_name(self):
        return self.field.name

    @abstractmethod
    def apply(self) -> set[str]:
        """Perform the sole canonical model transaction for this operation."""


@dataclass(frozen=True)
class FieldWriteEvent(FieldChangeEvent):
    value: Any

    def apply(self):
        from objectstate import ObjectStateRegistry
        with ObjectStateRegistry.defer_live_invalidations():
            return self.field.write(self.value)


@dataclass(frozen=True)
class FieldResetEvent(FieldChangeEvent):
    is_reset: ClassVar[bool] = True

    def apply(self):
        return self.field.reset()
''',
'FieldDispatchContext':'''@dataclass(frozen=True)
class FieldDispatchContext:
    """One prepared UI route; the event retains the field and source facts."""
    event: FieldChangeEvent
    root: "ParameterFormManager"

    @classmethod
    def for_event(cls, event):
        return cls(event, event.source_manager.form_tree.root())
''',
'FieldDispatchContextFactory':'',
'SourceStateUpdateStage':'''class SourceStateUpdateStage:
    """Apply the operation once, then synchronize the source view."""

    def run(self, context: FieldDispatchContext) -> set[str]:
        source = context.event.source_manager
        if source.before_mutation is not None:
            source.before_mutation()
        changed_paths = context.event.apply()
        source.sync_after_model_field_change(context.event.field_name, changed_paths=changed_paths)
        return changed_paths
'''}
for _,n in idx.indexed_nodes_of_type(ast.ClassDef):
 if n.name in bodies:
  a=min([n.lineno]+[d.lineno for d in n.decorator_list])-1;edits.append((a,n.end_lineno,bodies[n.name]))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t+'\n']
s=''.join(lines).replace('from contextlib import nullcontext\nfrom objectstate import DottedFieldPath, FieldProxy','from abc import ABC, abstractmethod\nfrom objectstate import FieldAccessError, FieldProxy').replace('from typing import TYPE_CHECKING, Any','from typing import TYPE_CHECKING, Any, ClassVar').replace('        self._context_factory = FieldDispatchContextFactory()\n','').replace('context = self._context_factory.build(event)','context = FieldDispatchContext.for_event(event)')
idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);offsets=[];at=0
for line in lines:offsets.append(at);at+=len(line)
edits=[]
for _,n in idx.indexed_nodes_of_type(ast.Attribute):
 text=None
 if isinstance(n.value,ast.Name)and n.value.id=='context':
  text={'source':'context.event.source_manager','field':'context.event.field','source_path':'context.event.field.address.value','root_path':'context.event.field.address.value'}.get(n.attr)
 elif isinstance(n.value,ast.Name)and n.value.id=='event'and n.attr=='value':text='event.field.raw'
 elif isinstance(n.value,ast.Attribute)and isinstance(n.value.value,ast.Name)and n.value.value.id=='context'and n.value.attr=='event'and n.attr=='value':text='context.event.field.raw'
 if text is not None:
  a=offsets[n.lineno-1]+len(lines[n.lineno-1].encode()[:n.col_offset].decode());b=offsets[n.end_lineno-1]+len(lines[n.end_lineno-1].encode()[:n.end_col_offset].decode());edits.append((a,b,text))
ordered=sorted(edits);assert all(a[1]<=b[0]for a,b in zip(ordered,ordered[1:])), 'overlapping admitted projections'
for a,b,t in reversed(ordered):s=s[:a]+t+s[b:]
compile(s,str(p),'exec');p.write_text(s)
# Reset policy no longer belongs to per-widget rendering services.
p=ROOT/'services/parameter_ops_service.py';s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True);edits=[]
for _,n in idx.indexed_nodes_of_type(ast.FunctionDef):
 if n.name in {'__init__','_get_effective_context_obj','_get_handler_prefix','reset_parameter'}or n.name.startswith('_reset_'):
  a=min([n.lineno]+[d.lineno for d in n.decorator_list])-1;edits.append((a,n.end_lineno,''))
for _,n in idx.indexed_nodes_of_type(ast.If):
 if isinstance(n.test,ast.Name)and n.test.id=='TYPE_CHECKING':edits.append((n.lineno-1,n.end_lineno,''))
for a,b,t in sorted(edits,reverse=True):lines[a:b]=[t]
s=''.join(lines).replace('class ParameterOpsService(ParameterServiceABC):','class ParameterOpsService:').replace('from objectstate import DottedFieldPath\n','').replace('from typing import TYPE_CHECKING\n','').replace('from formbridge.services.parameter_service_abc import ParameterServiceABC\n','')
s=s.replace('    # DELETED: _get_reset_value - ObjectState owns defaults\n    # DELETED: _update_reset_tracking - ObjectState.reset_parameter handles tracking\n','')
compile(s,str(p),'exec');p.write_text(s)
# The manager now issues one reset operation; no second reset publication path.
p=ROOT/'forms/parameter_form_chrome_sync.py';s=p.read_text();idx=module_syntax_index(SourceModule.from_source_path(p,s).parse().module);lines=s.splitlines(keepends=True)
for _,n in idx.indexed_nodes_of_type(ast.FunctionDef):
 if n.name=='dispatch_reset':lines[n.lineno-1:n.end_lineno]=[]
s=''.join(lines);compile(s,str(p),'exec');p.write_text(s)
