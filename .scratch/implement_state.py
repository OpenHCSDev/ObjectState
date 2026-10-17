"""Authored owner-level migration, with NRA-selected function spans.
Semantic changes are intentionally not claimed as automated equivalence proofs.
"""
import ast
from pathlib import Path
from nominal_refactor_advisor.ast_tools import SourceModule,module_syntax_index
ROOT=Path(__file__).resolve().parents[1]/'src/objectstate'

def replace_function(text,path,name,replacement):
 parsed=SourceModule.from_source_path(path,text).parse()
 matches=[n for _,n in module_syntax_index(parsed.module).indexed_nodes_of_type(ast.FunctionDef) if n.name==name]
 assert len(matches)==1,(path,name,len(matches))
 n=matches[0];lines=text.splitlines(keepends=True)
 start=min([n.lineno]+[d.lineno for d in n.decorator_list])-1
 return ''.join(lines[:start])+replacement.rstrip()+'\n'+''.join(lines[n.end_lineno:])

p=ROOT/'context_manager.py';text=p.read_text()
text=text.replace('from python_introspect import resolve_annotated, resolve_optional','from python_introspect import resolve_annotated, resolve_optional\nfrom objectstate.field_access import DataclassFieldAccess\nfrom objectstate.field_value import FieldValue')
text=text.replace('    ``scope_id`` is ``None`` for a layer entered without one. ``masks_outer_layers``\n    is True for a layer entered with ``mask_with_none``: a ``None`` in it is final,\n    so no layer outside it supplies a value.','    ``scope_id`` is ``None`` for a layer entered without one.')
text=text.replace('("scope_id", "obj", "masks_outer_layers", "_configs")','("scope_id", "obj", "_configs")').replace('def __init__(self, scope_id: str | None, obj: Any, masks_outer_layers: bool = False):','def __init__(self, scope_id: str | None, obj: Any):').replace('        self.masks_outer_layers = masks_outer_layers\n','')
text=replace_function(text,p,'_merge_nested_dataclass','''def _merge_nested_dataclass(base, override):
    """Merge stored values; Inherit delegates, while None is a concrete override."""
    return FieldValue.of(override).overlay(base, _merge_concrete_dataclass)


def _merge_concrete_dataclass(base, override):
    if not is_dataclass(base) or not is_dataclass(override):
        return override
    from objectstate.lazy_factory import get_base_type_for_lazy, replace_raw
    base_type = get_base_type_for_lazy(type(base)) or type(base)
    override_type = get_base_type_for_lazy(type(override)) or type(override)
    result_owner = base if base_type is override_type else override
    base_fields = DataclassFieldAccess.field_names(base)
    values = {
        f.name: _merge_nested_dataclass(
            DataclassFieldAccess.raw_value(base, f.name),
            DataclassFieldAccess.raw_value(override, f.name),
        )
        for f in fields(override) if f.name in base_fields
    }
    return replace_raw(result_owner, **values) if values else result_owner
''')
text=replace_function(text,p,'config_context','''@contextmanager
def config_context(obj, use_live_global: bool = True, scope_id: str | None = None):
    """Enter one layer. A stored None always supplies a concrete value."""
    from objectstate.config import get_base_config_type
    from objectstate.lazy_factory import replace_raw
    current = get_current_temp_global()
    base = current if current is not None else get_base_global_config(use_live=use_live_global)
    overrides = {}
    if obj is not None:
        read = DataclassFieldAccess.raw_value if is_dataclass(type(obj)) else getattr
        for declaration in fields(get_base_config_type()):
            try:
                value = read(obj, declaration.name)
            except AttributeError:
                continue
            base_value = DataclassFieldAccess.raw_value(base, declaration.name)
            overrides[declaration.name] = _merge_nested_dataclass(base_value, value)
    merged = replace_raw(base, **overrides) if overrides else base
    types = context_type_stack.get()
    stack = context_layer_stack.get() if current is not None else ContextLayerStack((ContextLayer("", base),))
    if obj is not None:
        stack = stack.with_layer(ContextLayer(scope_id, obj))
        types += (type(obj),)
    with ExitStack() as resources:
        for variable, value in ((current_temp_global, merged), (context_type_stack, types), (context_layer_stack, stack)):
            resources.callback(variable.reset, variable.set(value))
        yield merged
''')
text=replace_function(text,p,'build_context_stack','''@contextmanager
def build_context_stack(
    object_instance: object,
    ancestor_objects_with_scopes: Sequence[tuple[str, object]] = (),
    current_scope_id: str | None = None,
    use_live: bool = True,
):
    """Resolve against one explicit baseline and the recorded ancestor layers.

    Editing a global config starts from its declared defaults, not a live object
    hidden under a masking mode. Other states start from the selected global.
    """
    from objectstate.lazy_factory import GlobalConfigBase
    editing_global = isinstance(object_instance, GlobalConfigBase)
    baseline = type(object_instance)() if editing_global else get_base_global_config(use_live=use_live)
    layers = ContextLayerStack((ContextLayer("", baseline),))
    with ExitStack() as resources:
        for variable, value in ((current_temp_global, baseline), (context_type_stack, ()), (context_layer_stack, layers)):
            resources.callback(variable.reset, variable.set(value))
        for scope_id, ancestor in ancestor_objects_with_scopes:
            if not isinstance(ancestor, GlobalConfigBase):
                resources.enter_context(config_context(ancestor, use_live_global=use_live, scope_id=scope_id))
        resources.enter_context(config_context(object_instance, use_live_global=use_live, scope_id=current_scope_id))
        yield
''')
text=text.replace('A ``None`` override is kept: it means "inherit this field from the parent context".','A concrete ``None`` override is kept; only ``Inherit()`` requests inheritance.')
p.write_text(text)

p=ROOT/'lazy_factory.py';text=p.read_text()
text=text.replace('from contextlib import contextmanager','from contextlib import contextmanager\nfrom objectstate.field_value import FieldValue, Inherit, Unset\nfrom objectstate.field_access import DataclassFieldAccess')
text=text.replace('rebuild_with_none_defaults','rebuild_with_inherited_defaults').replace('field_names_to_none','inherited_field_names').replace('inherit_as_none','inherit_fields')
text=text.replace('make_optional(declared_type),\n                    field(\n                        default=None,','declared_type,\n                    field(\n                        default=Inherit(),')
text=text.replace('final_field_type = make_optional(field_type)','final_field_type = field_type')
text=text.replace('default=None,\n                        metadata=_inherited_default_metadata(field_definition)','default=Inherit(),\n                        metadata=_inherited_default_metadata(field_definition)')
text=replace_function(text,p,'patch_lazy_constructors','')
text=replace_function(text,p,'_get_raw_field_value','')
# Raw reconstruction must not invoke effective reads.
text=text.replace('object.__getattribute__(instance, f.name)','DataclassFieldAccess.raw_value(instance, f.name)')
text=text.replace('object.__getattribute__(self, f.name)','DataclassFieldAccess.raw_value(self, f.name)')
text=text.replace('object.__getattribute__(config, field_definition.name)','DataclassFieldAccess.raw_value(config, field_definition.name)')
text=text.replace('object.__getattribute__(\n                        inherited,\n                        field_definition.name,\n                    )','DataclassFieldAccess.raw_value(inherited, field_definition.name)')
text=text.replace('if value is not None:\n                return value','if not FieldValue.is_inherited(value):\n                return value')
start=text.index('            resolved_value = resolve_in_stack(stack, _cls, name).value')
end=text.index('\n        return __getattribute__',start)
text=text[:start]+'''            return value.resolve(lambda: resolve_in_stack(stack, _cls, name).value)
'''+text[end:]
p.write_text(text)

p=ROOT/'dual_axis_resolver.py';text=p.read_text()
text=text.replace('logger = logging.getLogger(__name__)','from objectstate.field_access import DataclassFieldAccess\nfrom objectstate.field_value import FieldValue, Unset\n\nlogger = logging.getLogger(__name__)')
text=replace_function(text,p,'_direct_owner_field_default','''def _direct_owner_field_default(config_type: type, field_name: str):
    """A declared own default, or Unset when this owner delegates the default."""
    if not is_dataclass(config_type):
        return Unset()
    declaration = config_type.__dataclass_fields__.get(field_name)
    if declaration is None or "_inherited_default" in declaration.metadata:
        return Unset()
    if declaration.default is not MISSING:
        return declaration.default
    if declaration.default_factory is not MISSING:
        return declaration.default_factory()
    return Unset()
''')
text=replace_function(text,p,'declared_default','''def declared_default(container_type: type, field_name: str) -> tuple[Any, type | None]:
    """Read the declared default, retaining an explicit None as a real value."""
    base = _normalize_to_base(container_type)
    own = _direct_owner_field_default(base, field_name)
    own_type = base if FieldValue.of(own).has_value else None
    if FieldValue.of(own).has_value:
        return own, own_type
    for owner in base.__mro__:
        value = getattr(owner, field_name, Unset())
        if FieldValue.of(value).has_value:
            return value, own_type
    if is_dataclass(container_type):
        for declaration in fields(container_type):
            if declaration.name != field_name:
                continue
            inherited = declaration.metadata.get("_inherited_default", MISSING)
            if inherited is not MISSING and FieldValue.of(inherited).has_value:
                return inherited, own_type
            factory = declaration.metadata.get("_inherited_default_factory", MISSING)
            if factory is not MISSING:
                return factory(), own_type
    return Unset(), own_type
''')
text=text.replace('''    visible_layers = []
    for layer in reversed(layers):
        visible_layers.append(layer)
        if layer.masks_outer_layers:
            break
''','''    visible_layers = tuple(reversed(layers))
''')
text=text.replace('object.__getattribute__(config_instance, field_name)','DataclassFieldAccess.raw_value(config_instance, field_name)')
text=text.replace('if value is not None:\n                return ResolvedField','if FieldValue.of(value).has_value:\n                return ResolvedField')
p.write_text(text)

# Constructor patching no longer exists: every normal constructor owns defaults.
p=ROOT/'__init__.py';text=p.read_text().replace('    patch_lazy_constructors,\n','').replace("    'patch_lazy_constructors',\n",'')
text+='\nfrom objectstate.field_value import FieldValue, Inherit, Unset\n'
# __all__ is the package export contract, not a fallback alias.
text=text.replace("    'LazyDataclass',","    'LazyDataclass',\n    'FieldValue',\n    'Inherit',\n    'Unset',")
p.write_text(text)
