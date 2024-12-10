# -*- coding: utf-8 -*-

"""
This module controls spectrometers from Ocean Optics Inc.
All spectrometers supported by python-seabreeze should work.
Please visit https://python-seabreeze.readthedocs.io/en/latest/index.html for more information.

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

from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.core.connector import Connector
from qudi.interface.spectrometer_interface import SpectrometerInterface
from qudi.hardware.camera.pixis_api import *
import numpy as np
import time


class PrincetonPICAM(SpectrometerInterface):
    """ Hardware module for reading spectra from the Ocean Optics spectrometer software.

    Example config for copy-paste:

    myspectrometer:
        module.Class: 'spectrometer.oceanoptics_spectrometer.OceanOptics'
        options:
            spectrometer_serial: 'QEP01583' #insert here the right serial number.

    """
    _camera = Connector(name='camera', interface='CameraInterface')
    _integration_time = StatusVar(name='integration_time', default=0.1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spectrometer = None

    def on_activate(self):
        """ Activate module.
        """
        self._camera = self._camera()
        self.wavelength = np.linspace(0, 1340, 1340)

        

    def on_deactivate(self):
        """ Deactivate module.
        """
        self._camera.disconnect()

    def record_spectrum(self):
        """ Record spectrum from Ocean Optics spectrometer.

            @return []: spectrum data
        """
      
        specdata = np.empty((2, len(self.wavelength)), dtype=np.double)
        specdata[0] = self.wavelength
        
        specdata[1] = self._camera.get_acquired_data().sum(axis=0)
        time.sleep(0.02)
        return specdata

    @property
    def exposure_time(self):
        """ Get exposure.
            @return float: exposure time
            Not implemented.
        """
        return self._camera.get_exposure() 

    @exposure_time.setter
    def exposure_time(self, value):
        """ Set exposure.
            @param float value: exposure time in seconds
        """
        assert isinstance(value, (float, int)), f'exposure_time needs to be a float in seconds, but was {value}'
        self._integration_time = float(value)
 
        self._camera.set_exposure(value)

    def clearBuffer(self):
        self._camera.stop_acquisition()