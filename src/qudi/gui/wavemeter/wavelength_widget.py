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

import pyqtgraph as pg
from typing import Tuple, Union, Sequence
from typing import Optional, List
from PySide2 import QtCore
from PySide2 import QtWidgets
import numpy as np
from qudi.util.colordefs import QudiPalettePale as palette
from qudi.util.widgets.toggle_switch import ToggleSwitch
from qudi.util.widgets.scientific_spinbox import ScienDSpinBox
from qudi.interface.scanning_probe_interface import ScanData, ScannerAxis, ScannerChannel

class WavelengthDataWidget(QtWidgets.QWidget):
    """
    """
    sigMarkerPositionChanged = QtCore.Signal(float)
    sigZoomAreaSelected = QtCore.Signal(tuple)
    
    def __init__(self,
                parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent=parent)

        main_layout = QtWidgets.QGridLayout()
        self.setLayout(main_layout)
        self.plot_widget = pg.PlotWidget(
            axisItems={'bottom': CustomAxis(orientation='bottom'),
                       'left'  : CustomAxis(orientation='left')}
        )
        self.plot_widget.getAxis('bottom').nudge = 0
        self.plot_widget.getAxis('left').nudge = 0
        self.plot_widget.showGrid(x=True, y=True, alpha=0.5)

        self._data_item = pg.PlotDataItem(pen=pg.mkPen(palette.c2))
        self.plot_widget.addItem(self._data_item)

        # Create an empty plot curve to be filled later, set its pen
        self.data_curve = self.plot_widget.plot()
        self.data_curve.setPen(palette.c1, width=2)

        self.plot_widget.setLabel('left', text='time', units='s')
        self.plot_widget.setLabel('bottom', text='frequency', units='Hz')
        self.plot_widget.setMinimumHeight(50)
        # vb = self._data_item.getViewBox()
        # vb.disableAutoRange()
        main_layout.addWidget(self.plot_widget)


        self._scan_data = None

    def set_plot_range(self,
                       x_range: Optional[Tuple[float, float]] = None,
                       y_range: Optional[Tuple[float, float]] = None
                       ) -> None:
        vb = self._data_item.getViewBox()
        
        vb.setRange(xRange=x_range, yRange=y_range)
        vb.disableAutoRange(axis="x")

    def set_data(self, data) -> None:
        # Save reference for channel changes
        # update_range = #(self._scan_data is None) or (self._scan_data.scan_range != data.scan_range) \
                       # or (self._scan_data.scan_resolution != data.scan_resolution)
        #self._scan_data = data
        # Set data
        self._update_scan_data(data)#, update_range=update_range)
    
    def set_fit_data(self, frequency, data):
        if data is None:
            self._data_item.clear()
        else:
            self._data_item.setData(y=data, x=frequency)

    #!! TODO choose CHANNEL
    def _update_scan_data(self, data, update_range=False) -> None:
    
        if data is None:
            self.data_curve.clear()
        else:
            if update_range:
                x_data = np.linspace(*self._scan_data.scan_range[0],
                                     self._scan_data.scan_resolution[0])
                self.data_curve.setData(x=self.data['wavelength'], y=x_data)
            else:
                self.data_curve.setData(x=data['wavelength'],
                                       y=data['time'])

class CustomAxis(pg.AxisItem):
    """ This is a CustomAxis that extends the normal pyqtgraph to be able to nudge the axis labels.
    """

    @property
    def nudge(self):
        if not hasattr(self, "_nudge"):
            self._nudge = 5
        return self._nudge

    @nudge.setter
    def nudge(self, nudge):
        self._nudge = nudge
        s = self.size()
        # call resizeEvent indirectly
        self.resize(s + QtCore.QSizeF(1, 1))
        self.resize(s)

    def resizeEvent(self, ev=None):
        # Set the position of the label
        nudge = self.nudge
        br = self.label.boundingRect()
        p = QtCore.QPointF(0, 0)
        if self.orientation == "left":
            p.setY(int(self.size().height() / 2 + br.width() / 2))
            p.setX(-nudge)
        elif self.orientation == "right":
            p.setY(int(self.size().height() / 2 + br.width() / 2))
            p.setX(int(self.size().width() - br.height() + nudge))
        elif self.orientation == "top":
            p.setY(-nudge)
            p.setX(int(self.size().width() / 2.0 - br.width() / 2.0))
        elif self.orientation == "bottom":
            p.setX(int(self.size().width() / 2.0 - br.width() / 2.0))
            p.setY(int(self.size().height() - br.height() + nudge))
        self.label.setPos(p)
        self.picture = None


