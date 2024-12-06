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
from qudi.interface.spectrometer_interface import SpectrometerInterface
from qudi.hardware.spectrometer.pixis_api import *
import numpy as np
import ctypes
from ctypes import c_int64, c_int, c_double, c_void_p, byref, POINTER, Structure, c_longlong
import time

FIXED_FRAME_SIZE = int(268000)

class PrincetonPICAM(SpectrometerInterface):
    """ Hardware module for reading spectra from the Ocean Optics spectrometer software.

    Example config for copy-paste:

    myspectrometer:
        module.Class: 'spectrometer.oceanoptics_spectrometer.OceanOptics'
        options:
            spectrometer_serial: 'QEP01583' #insert here the right serial number.

    """
    _library_path = ConfigOption(name='dll_path', default=None, missing='warn')
    _integration_time = StatusVar(name='integration_time', default=0.1)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spectrometer = None

    def on_activate(self):
        """ Activate module.
        """
        
        self.controller = SpectrometerController(self._library_path)
        self.wavelength = np.linspace(0, 1340, 1340)

        try:
            self.controller.initialize()
            cameras = self.controller.list_cameras()

            if not cameras:
                self.log.error("No cameras available. Please ensure the spectrometer is connected.")
                raise Exception("No cameras found.")

            self.log.info(f'Available spectrometers: {cameras}')
            self.controller.open_camera(cameras[0])  # Open the first available camera

            self.exposure_time = self.controller.get_exposure_time() / 1e3
            self.log.info(f'Exposure set to {self.exposure_time} seconds')

        except Exception as e:
            self.log.error(f"An error occurred during initialization: {e}")
            # Optionally, re-raise the exception if you want to stop further execution
            raise

    def on_deactivate(self):
        """ Deactivate module.
        """
        self.controller.close_camera()

    def record_spectrum(self):
        """ Record spectrum from Ocean Optics spectrometer.

            @return []: spectrum data
        """
      
        specdata = np.empty((2, len(self.wavelength)), dtype=np.double)
        specdata[0] = self.wavelength
        
        specdata[1] = self.controller.acquire_data()[1].sum(axis=0)
        time.sleep(0.02)
        return specdata

    @property
    def exposure_time(self):
        """ Get exposure.
            @return float: exposure time
            Not implemented.
        """
        return self.controller.get_exposure_time() / 1e3

    @exposure_time.setter
    def exposure_time(self, value):
        """ Set exposure.
            @param float value: exposure time in seconds
        """
        assert isinstance(value, (float, int)), f'exposure_time needs to be a float in seconds, but was {value}'
        self._integration_time = float(value)
 
        self.controller.set_exposure_time(float(self._integration_time * 1e3))# * 1e6))
       
        self.controller.commit_params()

    def clearBuffer(self):
        self.controller.stop_acquisition()