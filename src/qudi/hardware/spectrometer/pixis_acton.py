import numpy as np
from qtpy import QtCore

from qudi.interface.camera_interface import CameraInterface

from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.hardware.spectrometer.pixis_api import *
import numpy as np
import time


class Pixis(CameraInterface):
    """ Hardware class for Prime95B

    Example config for copy-paste:

    mycamera:
        module.Class: 'camera.prime95b.Prime95B'

    """
    # signals
    _library_path = ConfigOption(name='dll_path', default=None, missing='warn')
    _integration_time = StatusVar(name='integration_time', default=0.1)

    sigAcquisitionDone = QtCore.Signal(np.ndarray)

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self.controller = SpectrometerController(self._library_path)
        self.connect_to_cam()
        self._live = False

    def on_deactivate(self):
        """ Deinitialisation performed during deactivation of the module.
        """
        # stop acquisition
        # disconnect
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
        

    def get_name(self):
        """ Retrieve an identifier of the camera that the GUI can print

        @return string: name for the camera
        """
   
        return self.name

    def get_size(self):
        """ Retrieve size of the image in pixel

        @return tuple: Size (width, height)
        """
        shape = self.cam.shape()
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
