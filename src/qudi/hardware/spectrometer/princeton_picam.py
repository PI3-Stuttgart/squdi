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
from qtpy import QtCore
from qudi.core.connector import Connector
from qudi.interface.spectrometer_interface import SpectrometerInterface
from qudi.interface.camera_interface import CameraInterface
from qudi.hardware.spectrometer.acton_300i_api import *
from qudi.hardware.spectrometer.pixis_api import *
import numpy as np
import time


class PrincetonPICAM(SpectrometerInterface, CameraInterface):
    """ Hardware module for reading spectra from the Ocean Optics spectrometer software.

    Example config for copy-paste:

    myspectrometer:
        module.Class: 'spectrometer.oceanoptics_spectrometer.OceanOptics'
        options:
            spectrometer_serial: 'QEP01583' #insert here the right serial number.

    """
    _library_path = ConfigOption(name='dll_path', default=None, missing='warn')
    _integration_time = StatusVar(name='integration_time', default=0.1)
    _port = ConfigOption(name='port')
    offset_lam = 0
    my_wavelength = None
    sigAcquisitionDone = QtCore.Signal(np.ndarray)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._spectrometer = None
        self.dw0 = 68.5  # for 1200 g/mm
        

    def on_activate(self):
        """ Activate module.
        """
        self.controller = SpectrometerController(self._library_path)
        self.connect_to_cam()
        self._live = False

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
        self.disconnect()

    def connect_to_cam(self): # DO NOT CALL THIS FUNCTION connect. Will screw with signals somehow.
        """Createsa camera object using the first camera that is found.
        """
        try:
            self.controller.initialize()
            cameras = self.controller.list_cameras()

            if not cameras:
                self.log.error("No cameras available. Please ensure the spectrometer is connected.")
                raise Exception("No cameras found.")

            self.log.info(f'Available spectrometers: {cameras}')
            self.name = cameras[0]
            self.controller.open_camera(cameras[0])  # Open the first available camera

            self.exposure_time = self.controller.get_exposure_time() / 1e3
            self.log.info(f'Exposure set to {self.exposure_time} seconds')
            self.is_open = True

        except Exception as e:
            self.log.error(f"An error occurred during initialization: {e}")
            # Optionally, re-raise the exception if you want to stop further execution
            raise
        return
    
    def disconnect(self):
        self.controller.close_camera()
        self.is_open = False
        

    def record_spectrum(self):
        """ Record spectrum from Ocean Optics spectrometer.

            @return []: spectrum data
        """
        if self.my_wavelength:
            self.wavelength = self.my_wavelength
        specdata = np.empty((2, len(self.wavelength)), dtype=np.double)
        specdata[0] = self.wavelength
        
        specdata[1] = self.get_acquired_data().sum(axis=0)
        time.sleep(0.02)
        return specdata

    @property
    def exposure_time(self):
        """ Get exposure.
            @return float: exposure time
            Not implemented.
        """
        return self.get_exposure() 

    @exposure_time.setter
    def exposure_time(self, value):
        """ Set exposure.
            @param float value: exposure time in seconds
        """
        assert isinstance(value, (float, int)), f'exposure_time needs to be a float in seconds, but was {value}'
        self._integration_time = float(value)
 
        self.set_exposure(value)

    def clearBuffer(self):
        self.stop_acquisition()


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
        

    
    def get_name(self):
        """ Retrieve an identifier of the camera that the GUI can print

        @return string: name for the camera
        """
   
        return self.name

    def get_size(self):
        """ Retrieve size of the image in pixel

        @return tuple: Size (width, height)
        """
        shape = (1340, 100)
        return shape

    def support_live_acquisition(self):
        """ Return whether or not the camera can take care of live acquisition

        @return bool: True if supported, False if not
        """
        return False

    def get_gain(self):
        """ Get the gain

        @return float: exposure gain
        """
        
        return 1

    def set_gain(self, gain):
        """ Set the gain

        CAMERA ONLY SUPPORTS GAIN OF 1. THIS FUNCTION WILL ONLY SET THE GAIN TO 1.

        @param float gain: desired new gain

        @return float: new exposure gain
        """

        return 1

    def start_live_acquisition(self):
        """ Start a continuous acquisition.

        @return bool: Success ?
        """
        # self.cam.start_live()  
        # self._live = True

        return False

    def start_single_acquisition(self):
        """Should start a singel acquisition (specified by interface).

        Not implemented, so won't do anything.

        @return bool: Success ?
        """
        return False

    def stop_acquisition(self):
        """ Stop/abort live or single acquisition

        @return bool: Success ?
        """
        self.controller.stop_acquisition()
        return True

    def get_acquired_data(self):
        """ Acquires an image and returns it as array.

        This means after calling this function, the camera acquires a picture for the set exposure time
        and then sends the array. Depending on the set exposure time this may need some time.

        @return numpy array: image data in format [[row],[row]...]

        Each pixel might be a float, integer or sub pixels
        """
        image_array = self.controller.acquire_data()[1]
        time.sleep(0.1)
        image_array = np.array(image_array)

        return image_array

    def emit_acquired_data(self):
        img = self.get_acquired_data()
        self.sigAcquisitionDone.emit(img)
        time.sleep(0.1)
        return

    def get_exposure(self):
        """ Get the exposure time in seconds

        @return float: exposure time
        """
        exp_time = self.controller.get_exposure_time() / 1e3
        return exp_time

    def set_exposure(self,exposure):
        """Sets the exposure time in s.

        @param float exposure: desired new exposure time

        @return float: setted new exposure time
        """
        self.controller.set_exposure_time(float(exposure * 1e3))# * 1e6))
       
        self.controller.commit_params()
        return exposure

    def _set_exposure(self, exp_time):
        """Set the exposure time to exp_time. Units are given by exp_res_index.
        """
        self.exp_time = exp_time
        return

    def get_ready_state(self):
        """ Is the camera ready for an acquisition ?

        @return bool: ready ?
        """
        if self.is_open:
            return True
        else:
            return False
