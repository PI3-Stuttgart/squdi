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

class PLEDataWidget(QtWidgets.QWidget):
    """
    """
    sigMarkerPositionChanged = QtCore.Signal(float)
    sigZoomAreaSelected = QtCore.Signal(tuple)

    def __init__(self,
                axis: Tuple[ScannerAxis],
                channel: ScannerChannel,
                parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent=parent)

        main_layout = QtWidgets.QGridLayout()
        self.setLayout(main_layout)
        self._channel = channel
        self.axis = axis
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
        self.data_curve.setPen(palette.c1, width=1)

        self.selected_region = pg.LinearRegionItem(
                                              brush=pg.mkBrush(122, 122, 122, 30),
                                              hoverBrush=pg.mkBrush(196, 196, 196, 30))
        self.plot_widget.addItem(self.selected_region)

        self.target_point = pg.InfiniteLine(
                                            angle=90,
                                            movable=True,
                                            pen=pg.mkPen(color='green', width=2))
        self.plot_widget.addItem(self.target_point)

        self.plot_widget.setLabel('left', text=channel.name, units=channel.unit)
        self.plot_widget.setLabel('bottom', text=axis.name.title(), units=axis.unit)
        self.plot_widget.setMinimumHeight(50)
        main_layout.addWidget(self.plot_widget)


        self._scan_data = None

    def set_scan_data(self, plot_data, data: ScanData) -> None:
        # Save reference for channel changes
        update_range = (self._scan_data is None) or (self._scan_data.scan_range != data.scan_range) \
                        or (self._scan_data.scan_resolution != data.scan_resolution)
        self._scan_data = data
        self._plot_data = plot_data
        # Set data
        self._update_scan_data(update_range=update_range)
    
    @property
    def channel(self):
        return self._channel

    @channel.setter
    def channel(self, ch):
        self._channel = ch
        self.plot_widget.setLabel('left', text=ch.name, units=ch.unit)
        self.plot_widget.setLabel('bottom', text=self.axis.name.title(), units=self.axis.unit)
        self._update_scan_data(False)

    def set_fit_data(self, frequency, data):
        if data is None:
            self._data_item.clear()
        else:
            self._data_item.setData(y=data, x=frequency)

    #!! TODO choose CHANNEL
    def _update_scan_data(self, update_range: bool) -> None:
        current_channel = self._channel.name #or APD events ?? or time tagger #!TODO!
        if (self._scan_data is None) or (self._plot_data is None):
            self.data_curve.clear()

        else:
            x_data = np.linspace(*self._scan_data.scan_range[0],
                                     self._scan_data.scan_resolution[0])
            if update_range:
                self.data_curve.setData(y=self._plot_data[current_channel], x=x_data)
                self.selected_region.setRegion(self._scan_data.scan_range[0])
                # self.target_point.setValue(self._scan_data.scan_range[0][0])
            else:
                self.data_curve.setData(y=self._plot_data[current_channel],
                                       x=x_data)#self.data_curve.xData)

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


