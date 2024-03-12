# -*- coding: utf-8 -*-
"""
This module contains the data display and analysis widget for SpectrometerGui.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""

__all__ = ['PLEDataWidget']


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
class MatrixCountlogDataWidget(QtWidgets.QWidget):
    """
    """
    sigMarkerPositionChanged = QtCore.Signal(float)
    sigZoomAreaSelected = QtCore.Signal(tuple)

    def __init__(self,
                parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent=parent)

        main_layout = QtWidgets.QGridLayout()
        self.setLayout(main_layout)
        matrix_group_box = QtWidgets.QGroupBox('Matrix Region')
        self.image_widget = ImageWidget(colorscale = ColorScale) #_Colorscale().lut
        self.image_item = self.image_widget.image_item

        self.image_widget.set_axis_label('left', label="Scans", unit="#")
        self.image_widget.set_axis_label('bottom', label="wavelength", unit="THz")
        self.image_widget.set_data_label(label="Counts", unit="cts")

        self.layout().addWidget(self.image_widget)

        # disable buggy pyqtgraph 'Export..' context menu
        self.image_widget.plot_widget.setAspectLocked(lock=False, ratio=1.0)
        self.image_widget.plot_widget.getPlotItem().vb.scene().contextMenu[0].setVisible(False)

        self.number_of_repeats=None
        self._scan_data = None
    
    def set_plot_range(self,
                       x_range: Optional[Tuple[float, float]] = None,
                       y_range: Optional[Tuple[float, float]] = None
                       ) -> None:
        vb = self.image_item.getViewBox()
        vb.setRange(xRange=x_range, yRange=y_range)

    def _update_scan_data(self) -> None:
       
        current_channel = self.channel.name 

        self.image_widget.set_image(self._scan_data.accumulated_data[current_channel].T)    
        matrix_range = (self._scan_data.scan_range[0], (0, self._scan_data.accumulated_data[current_channel].shape[0]))
        self.image_widget.set_image_extent(matrix_range,
                        adjust_for_px_size=True)
        self.image_widget.autoRange()
    
    def set_fit_data(self, frequency, data):
        if data is None:
            self._data_item.clear()
        else:
            self._data_item.setData(y=data, x=frequency)

    def _update_scan_data(self, data, update_range: bool) -> None:
        if data is None:
            self.data_curve.clear()
        else:
            if update_range:
                x_data = np.linspace(*self._scan_data.scan_range[0],
                                     self._scan_data.scan_resolution[0])
                self.data_curve.setData(y=data['counts'], x=data['wavelength'])
                self.selected_region.setRegion(self._scan_data.scan_range[0])
            else:
                self.data_curve.setData(y=data['counts'],
                                       x=data['wavelength'])
            self.image_widget.set_image(self._scan_data.accumulated_data[current_channel].T)    
            matrix_range = (self._scan_data.scan_range[0], (0, self._scan_data.accumulated_data[current_channel].shape[0]))
            self.image_widget.set_image_extent(matrix_range,
                            adjust_for_px_size=True)
            self.image_widget.autoRange()