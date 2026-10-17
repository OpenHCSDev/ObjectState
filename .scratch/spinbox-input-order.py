from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest
from pyqt_reactive.protocols import SpinBoxAdapter
class TracedSpin(SpinBoxAdapter):
    def _native_input(self,*args):
        print('INPUT before',args,'sender-line',self.sender() is self.lineEdit(),'value',self.value(),'text',self.text(),'draft',type(self._draft).__name__,'blocked',self.signalsBlocked(),flush=True)
        super()._native_input(*args)
        print('INPUT after','value',self.value(),'text',self.text(),'draft',type(self._draft).__name__,'blocked',self.signalsBlocked(),flush=True)
a=QApplication([]); w=TracedSpin();w.show();w.configure_range(-10,10)
w.connect_change_signal(lambda v:print('CALLBACK',v,flush=True))
w.valueChanged.connect(lambda v: print('QT valueChanged',v,'read',w.value(),'text',w.text(),flush=True))
w.lineEdit().textEdited.connect(lambda t:print('QT textEdited',repr(t),'read',w.value(),'text',w.text(),flush=True))
w.set_value(None);print('PAINTED',w.value(),w.text(),flush=True)
w.lineEdit().selectAll();QTest.keyClicks(w.lineEdit(),'0');print('FINAL',w.value(),w.text(),w.get_value(),flush=True)
