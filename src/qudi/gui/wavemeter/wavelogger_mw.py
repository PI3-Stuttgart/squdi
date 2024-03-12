
from PySide2 import QtCore, QtGui, QtWidgets
import pyqtgraph as pg
import qudi.util.uic as uic
import os
from qudi.util.widgets.advanced_dockwidget import AdvancedDockWidget
from qudi.util.widgets.fitting import FitWidget
import importlib
from qudi.interface.scanning_probe_interface import ScanData, ScannerAxis, ScannerChannel
from typing import Tuple, Union, Sequence
from typing import Optional, List
try:
    importlib.reload(wavelength_widget)
except NameError:
    import qudi.gui.wavemeter.wavelength_widget as wavelength_widget
try:
    importlib.reload(countlog_widget)
except NameError:
    import qudi.gui.wavemeter.countlog_widget as countlog_widget

try:
    importlib.reload(matrix_countlog_widget)
except NameError:
    import qudi.gui.wavemeter.matrix_countlog_widget as matrix_countlog_widget



class WavemeterMainWindow(QtWidgets.QMainWindow):

    def __init__(self,
                parent: Optional[QtWidgets.QWidget] = None):
       
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_scanwindow.ui')
        # Load it
        super(WavemeterMainWindow, self).__init__()
        uic.loadUi(ui_file, self)
        self.show()

        self.centralwidget.hide()

        self.wavelength_widget = wavelength_widget.WavelengthDataWidget()
        self.wavelength_dockWidget.setWidget(self.wavelength_widget)

        self.countlog_widget = countlog_widget.CountlogDataWidget()
        self.counts_log_dockWidget.setWidget(self.countlog_widget)

        self.matrix_countlog_widget = matrix_countlog_widget.MatrixCountlogDataWidget()
        self.matrix_counts_log_dockWidget.setWidget(self.matrix_countlog_widget)


    def restore_view(self):
        # Resize main window
        # screen_size = QtWidgets.QApplication.instance().desktop().availableGeometry(self).size()
        # self.resize(screen_size.width() // 3, screen_size.height() // 2)

        # Rearrange DockWidget
        # if not self.action_show_data.isChecked():
        self.data_dockwidget.show()
        self.data_dockwidget.setFloating(False)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self.data_dockwidget)
