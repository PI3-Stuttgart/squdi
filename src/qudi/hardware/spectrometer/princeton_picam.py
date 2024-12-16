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
from qudi.hardware.spectrometer.acton_300i_api import *
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
    _port = ConfigOption(name='port')
    offset_lam = 0
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spectrometer = None
        self.dw0 = 68.5  # for 1200 g/mm
        

    def on_activate(self):
        """ Activate module.
        """
        self._camera = self._camera()
        self._spectrometer = Acton300i(self._port)
        self._clam = self.cwavelength
        self._grating = self.grating
        # self.wavelength = np.linspace(0, 1340, 1340)
        self.dw = 2*self.dw0 / 3 # for 1800 g/mm
        
        self.dw =  2*self.dw0 / 3 if self._grating == 2 else 4* self.dw0
        self.wavelength = np.linspace(self._clam - self.dw/2, self._clam + self.dw/2, 1340) + self.offset_lam

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


    @property
    def grating(self):
        """ Get current grating.
            @return int: current grating number
        """
        self._grating = self._spectrometer.get_current_grating()
        return self._grating 

    @grating.setter
    def grating(self, value):
        """ Set grating.
            @param int value: grating number to set (typically 1 or 2)
        """
        assert isinstance(value, (float, int)), f'grating needs to be a number, but was {value}'
        self._spectrometer.set_grating(int(value))
        
        self._grating = int(value)
        self.dw =  2*self.dw0 / 3 if self._grating == 2 else 4* self.dw0
        self.wavelength = np.linspace(self._clam - self.dw/2, self._clam + self.dw/2, 1340) + self.offset_lam
    
    @property
    def cwavelength(self):
        """ Get center wavelength.
            @return float: current center wavelength in meters
        """

        self._clam = self._spectrometer.get_current_wavelength_value()
        return self._clam
    
    @cwavelength.setter
    def cwavelength(self, value):
        """ Set center wavelength.
            @param float value: center wavelength in meters
        """
        assert isinstance(value, (float, int)), f'center wavelength needs to be a number in meters, but was {value}'
        self._spectrometer.set_wavelength(float(value))
        self._clam = value
        self.wavelength = np.linspace(self._clam - self.dw/2, self._clam + self.dw/2, 1340) + self.offset_lam
        