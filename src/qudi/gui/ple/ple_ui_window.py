
from PySide2 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
import qudi.util.uic as uic
import os
from qudi.util.widgets.advanced_dockwidget import AdvancedDockWidget
from qudi.util.widgets.fitting import FitWidget
import importlib
from qudi.interface.scanning_probe_interface import ScanData, ScannerAxis, ScannerChannel
from qudi.gui.ple.ple_repump_widget import PleMicrowaveWidget, PlePulsedWidget
from qudi.gui.ple.controller_widget import ControllerWidget
from typing import Tuple, Union, Sequence
from typing import Optional, List
try:
    importlib.reload(ple_data_widget)
except NameError:
    import qudi.gui.ple.ple_data_widget as ple_data_widget

try:
    importlib.reload(matrix_widget)
except NameError:
    import qudi.gui.ple.matrix_widget as matrix_widget



class PLEScanMainWindow(QtWidgets.QMainWindow):

    def __init__(self,
                axes: Tuple[ScannerAxis],
                channel: ScannerChannel,
                parent: Optional[QtWidgets.QWidget] = None):
       
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ple_gui.ui')
        # Load it
        super(PLEScanMainWindow, self).__init__()
        uic.loadUi(ui_file, self)
        self.show()

        self.centralwidget.hide()

        self.ple_widget = ple_data_widget.PLEDataWidget(axes, channel)
        self.ple_data_dockWidget.setWidget(self.ple_widget)

        self.ple_averaged_widget = ple_data_widget.PLEDataWidget(axes, channel)
        self.ple_averaged_dockWidget.setWidget(self.ple_averaged_widget)

        self.matrix_widget = matrix_widget.PLE2DWidget(axes, channel)
        self.ple_matrix_dockWidget.setWidget(self.matrix_widget) 

    def add_dock_widget(self, name):

        if name == 'Microwave':
            setattr(self, f"{name}_widget", PleMicrowaveWidget())
        elif name == "Pulsed":
            setattr(self, f"{name}_widget", PlePulsedWidget(name))
        elif name == "Controller":
            setattr(self, f"{name}_widget", ControllerWidget(name))
        setattr(self, f"{name}_dockWidget", QtWidgets.QDockWidget())
        dockWidget = getattr(self, f"{name}_dockWidget")
        dockWidget.setObjectName(name)
        dockWidget.setWindowTitle(name)
        dockWidget.setFloating(False)

        widget = getattr(self, f"{name}_widget")
        self.addDockWidget(QtCore.Qt.TopDockWidgetArea, dockWidget)
        dockWidget.setWidget(widget)


    def restore_view(self):
        # Resize main window
        # screen_size = QtWidgets.QApplication.instance().desktop().availableGeometry(self).size()
        # self.resize(screen_size.width() // 3, screen_size.height() // 2)

        # Rearrange DockWidget
        # if not self.action_show_data.isChecked():
        self.data_dockwidget.show()
        self.data_dockwidget.setFloating(False)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.data_dockwidget)
