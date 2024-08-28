# coding=utf-8
from __future__ import print_function, absolute_import, division
__metaclass__ = type

import traceback
import sys
import os

import PySide2.QtWidgets
import PySide2.QtCore
import qudi.util.uic as uic

def compile_ui_file(ui_filepath):
    name = os.path.basename(ui_filepath).split('.')[0] + '.py'
    py_filepath = os.path.join(os.path.dirname(ui_filepath), name)
    with open(py_filepath, 'w') as f:
        uic.compileUi(ui_filepath, f)



class WithQt:

    def __init__(self, parent=None, gui=None, QtGuiClass=None, **kwargs):
        super(WithQt, self).__init__()
        if gui:
            self.QtGuiClass = QtGuiClass
            self.init_gui(parent)
            self.gui.show()

    def init_gui(self, parent=None):
        self._gui = self.QtGuiClass(no_qt=self, parent=parent)

    @property
    def window_title(self):
        try:
            return self._window_title
        except:
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)

    def update_window_title(self, val):
        try:
            self._window_title = str(val)
            if hasattr(self, '_gui'):
                self.gui.update_window_title(self.window_title)
        except:
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)

    @property
    def gui(self):
        try:
            return self._gui
        except:
            exc_type, exc_value, exc_tb = sys.exc_info()
            traceback.print_exception(exc_type, exc_value, exc_tb)


class QtGuiClass(PySide2.QtWidgets.QMainWindow):
    clear_signal = PySide2.QtCore.Signal()
    show_signal = PySide2.QtCore.Signal()
    close_signal = PySide2.QtCore.Signal()
    update_window_title_signal = PySide2.QtCore.Signal(str)

    def __init__(self, parent=None, no_qt=None, ui_filepath=None):
        super(QtGuiClass, self).__init__(parent=parent)
        self.no_qt = no_qt
        self.ui_filepath = ui_filepath

        uic.loadUi(self.ui_filepath, self)
        # It was working! But not connected to the Fields...
        # widget = PySide2.QtWidgets.QWidget()
        #PySide2.uic.loadUi(self.ui_filepath, widget)
        #self.setCentralWidget(widget)
        #self.setCentralWidget(self.parameter_tab)
        self.init_gui()


    def init_gui(self):
        for name in [
            'clear',
            'update_window_title',
        ]:
            getattr(getattr(self, "{}_signal".format(name)), 'connect')(getattr(self, "{}_signal_emitted".format(name)))

        self.show_signal.connect(self.show)
        self.close_signal.connect(self.close)

    def clear(self):
        self.clear_signal.emit()

    def show_gui(self):
        self.show_signal.emit()

    def close_gui(self):
        self.close_signal.emit()

    def update_window_title(self, val):
        self.update_window_title_signal.emit(val)

    def update_window_title_signal_emitted(self, val):
        self.setWindowTitle(val)