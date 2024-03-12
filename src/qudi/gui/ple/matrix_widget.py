
import os
import numpy as np
from typing import Tuple, Union, Sequence
from PySide2 import QtCore, QtWidgets, QtGui
from typing import Optional, List
from qudi.util.widgets.plotting.plot_widget import PlotWidget
from qudi.util.widgets.plotting.image_widget import ImageWidget
from qudi.util.widgets.plotting.plot_item import XYPlotItem
from qudi.util.paths import get_artwork_dir

from qudi.util.colordefs import ColorScaleRdBuRev as ColorScale
from pyqtgraph import mkPen, mkBrush, PlotWidget, BarGraphItem

from qudi.interface.scanning_probe_interface import ScanData, ScannerAxis, ScannerChannel

class PLE2DWidget(QtWidgets.QWidget):
    """ Widget to interactively display multichannel 2D scan data as well as toggling and saving
    scans.
    """

    def __init__(self,
                axis: Tuple[ScannerAxis],
                channel: ScannerChannel,
                parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent=parent)

        
        main_layout = QtWidgets.QGridLayout()
        self.setLayout(main_layout)

        self._channel = channel
        self.axis = axis
        matrix_group_box = QtWidgets.QGroupBox('Matrix Region')
        self.image_widget = ImageWidget(colorscale = ColorScale) #_Colorscale().lut
        self.image_item = self.image_widget.image_item

        self.image_widget.set_axis_label('left', label=self._channel.name, unit=self._channel.unit)
        self.image_widget.set_axis_label('bottom', label=self.axis.name.title(), unit=self.axis.unit)
        self.image_widget.set_data_label(label=self._channel.name, unit=self._channel.unit)
        
        self.layout().addWidget(self.image_widget)
        
        # disable buggy pyqtgraph 'Export..' context menu
        self.image_widget.plot_widget.setAspectLocked(lock=False, ratio=1.0)
        self.image_widget.plot_widget.getPlotItem().vb.scene().contextMenu[0].setVisible(False)
    
        self.number_of_repeats=None
        self._scan_data = None

    @property
    def channel(self):
        return self._channel

    @channel.setter
    def channel(self, ch):
        self._channel = ch
        self.image_widget.set_axis_label('left', label=self._channel.name, unit=self._channel.unit)
        self.image_widget.set_axis_label('bottom', label=self.axis.name.title(), unit=self.axis.unit)
        self.image_widget.set_data_label(label=self._channel.name, unit=self._channel.unit)
        self._update_scan_data()

    def set_plot_range(self,
                       x_range: Optional[Tuple[float, float]] = None,
                       y_range: Optional[Tuple[float, float]] = None
                       ) -> None:
        vb = self.image_item.getViewBox()
        vb.setRange(xRange=x_range, yRange=y_range)

    def set_scan_data(self, plot_data, scan_data: ScanData) -> None:
        self._scan_data = scan_data
        self._plot_data = plot_data
        self._update_scan_data()

    def _update_scan_data(self) -> None:
       
        current_channel = self._channel.name 
        
        if self._scan_data is not None and (self._plot_data is not None):
            self.image_widget.set_image(self._plot_data[current_channel].T)    
            matrix_range = (self._scan_data.scan_range[0], (0, self._plot_data[current_channel].shape[0]))
            self.image_widget.set_image_extent(matrix_range,
                            adjust_for_px_size=True)
            self.image_widget.autoRange()
