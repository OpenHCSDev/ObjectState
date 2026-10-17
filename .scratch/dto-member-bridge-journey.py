"""Production Qt dispatch, authenticated ZMQ bridge, typed DTOs and retained history."""
import concurrent.futures
import json
import runpy
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QObject, QEventLoop, QTimer, pyqtSignal
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from objectstate import Inherit, LazyDataclassFactory, ObjectState, ObjectStateRegistry, Unset, set_base_config_type, set_global_config
from objectstate.field_value import Value
from python_introspect import to_jsonable
from pyqt_reactive.forms.parameter_form_manager import ParameterFormManager
from pyqt_reactive.services.ui_thread_dispatch import UiThreadDispatcher
from formbridge.bridge.dto import UiObjectStateFieldMutationRequest, UiObjectStateScopeListRequest
from formbridge.bridge.in_process import UiAgentBridgeService
from formbridge.bridge.object_state import ObjectStateScopeProvider
from formbridge.bridge.server import UiBridgeControlServer, UiBridgeServerConfig
from formbridge.bridge.service import UiBridgeService, UiBridgeListObjectStateScopesOperation, UiBridgeMutateObjectStateFieldOperation
from zmqruntime.config import TransportMode

runpy.run_path('/home/ts/wt/formbridge-declared-fields/tests/conftest.py')
app = QApplication([])
@dataclass
class Settings:
    text: str | None = None
    count: int = 0
set_base_config_type(Settings)
set_global_config(Settings, Settings(text='global', count=7))
lazy = LazyDataclassFactory.make_lazy_simple(Settings)
state = ObjectState(lazy(text=None, count=0), scope_id='dto-member-journey')
ObjectStateRegistry.register(state)
field = state.fields.text
manager = ParameterFormManager(state)
build = QEventLoop()
manager.register_form_build_completion_callback(build.quit)
if not manager.form_build_complete:
    QTimer.singleShot(2000, build.quit)
    build.exec()
assert manager.form_build_complete and manager.form_build_failure is None
manager.show()
app.processEvents()

class Completion(QObject):
    done = pyqtSignal()
completion = Completion()

def call(pool, operation, request):
    loop = QEventLoop()
    completion.done.connect(loop.quit)
    future = pool.submit(client.invoke, operation, request, connection)
    future.add_done_callback(lambda _: completion.done.emit())
    if not future.done():
        QTimer.singleShot(5000, loop.quit)
        loop.exec()
    completion.done.disconnect(loop.quit)
    result = future.result(timeout=0)
    assert not result.errors, result.errors
    return result

root = Path('/home/ts/.cache/agent-scratch/objectstate-declared-fields')
with tempfile.TemporaryDirectory(prefix='dto-bridge-', dir=root) as directory:
    bridge = UiAgentBridgeService(dispatcher=UiThreadDispatcher())
    bridge.register_object_state_scope_provider(ObjectStateScopeProvider())
    server = UiBridgeControlServer(bridge, UiBridgeServerConfig(
        port=None, transport_mode=TransportMode.TCP,
        descriptor_directory_path=Path(directory),
    ))
    binding = server.start()
    client = UiBridgeService()
    connection = client.connection_from_args(descriptor_file_path=binding.descriptor_file_path)
    receipts = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            query = UiObjectStateScopeListRequest(include_fields=True, include_field_values=True)
            for datum in (None, '', 'None'):
                request = UiObjectStateFieldMutationRequest.from_fields(
                    object_state_scope_id=state.scope_id, field_path='text', value=datum,
                )
                mutation = call(pool, UiBridgeMutateObjectStateFieldOperation, request)
                assert mutation.mutated and field.raw == datum
                assert mutation.after.raw_value == Value(datum)
                assert mutation.after.resolved_value == Value(datum)
                catalog = call(pool, UiBridgeListObjectStateScopesOperation, query)
                rows = [row for scope in catalog.scopes for row in scope.fields if row.field_name == 'text']
                assert len(rows) == 1 and rows[0].raw_value == Value(datum)
                assert rows[0].resolved_value == Value(datum)
                assert manager.widgets['text'].get_value() == datum
                receipts.append(to_jsonable(rows[0])['raw_value'])
            reset = call(pool, UiBridgeMutateObjectStateFieldOperation,
                UiObjectStateFieldMutationRequest.from_fields(
                    object_state_scope_id=state.scope_id, field_path='text', reset=True,
                ))
            assert reset.mutated and reset.after.raw_value == Inherit()
            assert reset.after.resolved_value == Value('global')
            assert ObjectStateRegistry.time_travel_back()
            app.processEvents()
            assert field.raw == 'None' and manager.widgets['text'].get_value() == 'None'
            edit = manager.widgets['text']
            edit.selectAll()
            QTest.keyClicks(edit, 'native')
            wait = QEventLoop()
            release = state.fields.subscribe(lambda _: wait.quit() if field.raw == 'native' else None)
            if field.raw != 'native':
                QTimer.singleShot(1000, wait.quit)
                wait.exec()
            release()
            assert field.raw == 'native'
            catalog = call(pool, UiBridgeListObjectStateScopesOperation, query)
            row = next(row for scope in catalog.scopes for row in scope.fields if row.field_name == 'text')
            assert row.raw_value == Value('native') and row.resolved_value == Value('native')
            state.fields.text.write(Unset())
            catalog = call(pool, UiBridgeListObjectStateScopesOperation, query)
            row = next(row for scope in catalog.scopes for row in scope.fields if row.field_name == 'text')
            assert row.raw_value == Unset() and row.resolved_value == Unset()
            assert to_jsonable(row)['raw_value'] == {'Unset': {}}
    finally:
        server.stop()
        bridge.close()
        manager.dispose()
        manager.close()
        manager.deleteLater()
        ObjectStateRegistry.unregister(state)
        app.processEvents()
print(json.dumps({'journey':'real Qt native input, main-thread dispatch, authenticated ZMQ server/client, DTO decode, reset, history undo and view disposal','raw_wire_members':receipts,'inheritance':True,'absence':True,'source_paired_not_installed':True,'providers':0}))
