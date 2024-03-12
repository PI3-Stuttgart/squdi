__all__ = ('PleFitDockWidget',)

from PySide2 import QtWidgets
from qudi.util.widgets.fitting import FitWidget


class PleFitDockWidget(QtWidgets.QDockWidget):
    """
    """

    def __init__(self, *args, fit_container=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.setWindowTitle('PLE Fit')
        self.setObjectName('ple_fit_dockwidget')
        self.setFeatures(self.DockWidgetFloatable | self.DockWidgetMovable)

        self.fit_widget = FitWidget(fit_container=fit_container)
        self.setWidget(self.fit_widget)
