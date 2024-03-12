import numpy as np
from qtpy import QtCore

from qudi.interface.camera_interface import CameraInterface

from pyvcam import pvc # Get it here: https://github.com/Photometrics/PyVCAM
from pyvcam.camera import Camera
from pyvcam import constants as const

class Prime95B(CameraInterface):
    """ Hardware class for Prime95B

    Example config for copy-paste:

    mycamera:
        module.Class: 'camera.prime95b.Prime95B'

    """
    # signals
    sigAcquisitionDone = QtCore.Signal(np.ndarray)

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        self.connect_to_cam() # connect to camera
        a = self.set_fan_speed(0) # 0 means high
        a = self.set_exposure_mode('Internal Trigger')
        a = self.set_exposure(0.1)
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
        pvc.init_pvcam() # initializes pvcam
        self.cam = next(Camera.detect_camera()) # Generator function to detect a connected camera (specifically: first camera)
        self.cam.open() # open the camera
        return

    def disconnect(self):
        self.cam.close()
        return

    def get_name(self):
        """ Retrieve an identifier of the camera that the GUI can print

        @return string: name for the camera
        """
        name = self.cam.name
        return name

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
        return True

    def start_live_acquisition(self):
        """ Start a continuous acquisition.

        @return bool: Success ?
        """
        self.cam.start_live()  
        self._live = True

        return True

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
        if self._live:
            self._live = False
            self.cam.finish()
        return True

    def get_acquired_data(self):
        """ Acquires an image and returns it as array.

        This means after calling this function, the camera acquires a picture for the set exposure time
        and then sends the array. Depending on the set exposure time this may need some time.

        @return numpy array: image data in format [[row],[row]...]

        Each pixel might be a float, integer or sub pixels
        """
        image_array = self.cam.get_frame()
        image_array = np.array(image_array)

        return image_array

    def emit_acquired_data(self):
        img = self.get_acquired_data()
        self.sigAcquisitionDone.emit(img)
        return

    def get_exposure(self):
        """ Get the exposure time in seconds

        @return float: exposure time
        """
        exp_time = self.cam.exp_time
        exp_res = self.get_exposure_res()
        exp_res_dict = {0: 1e-3, 1: 1e-6}
        fac = exp_res_dict[exp_res] # turn ms into s and us into s
        exp_time = float(exp_time*fac)
        return exp_time

    def get_max_exposure(self):
        """ Gets the maximal exposure value (unitless).
        """
        max_value_exp_time = self.cam.get_param(const.PARAM_EXPOSURE_TIME,const.ATTR_MAX)
        return max_value_exp_time

    def convert_exposure_time(self,exposure):
        """Converts the exposure time from seconds to tiem and resoltion.
        
        @param float exposure: desired new exposure time in seconds

        @return int,int: resolution of the exposure time and exposure time in correct unit
        """
        exp_time = exposure*1e3 # we are working in ms
        max_value_exp_time = self.get_max_exposure()
        if exp_time < 1e-3:
            print(f'exposure time of {exposure} s is too small. Setting it to 1 ms.')
            exp_time = 1
            exp_res = 1
        if 1e-3 <= exp_time < 1: # here we need us
            exp_time = int(exp_time * 1e3)
            exp_res = 1
        elif 1 <= exp_time <= max_value_exp_time: # here we need ms
            exp_time = int(exp_time)
            exp_res = 0
        else:
            print(f'exposure time of {exposure} s is too big. Setting it to {int(max_value_exp_time*1e-3)} s.')
            exp_time = int(max_value_exp_time)
            exp_res = 1
        return exp_res,exp_time

    def set_exposure(self,exposure):
        """Sets the exposure time in s.

        @param float exposure: desired new exposure time

        @return float: setted new exposure time
        """
        exp_res,exp_time = self.convert_exposure_time(exposure)
        self._set_exposure(exp_time)
        self.set_exposure_res(exp_res)
        new_exposure = self.get_exposure()
        return new_exposure

    def _set_exposure(self, exp_time):
        """Set the exposure time to exp_time. Units are given by exp_res_index.
        """
        self.exp_time = self.cam.exp_time = exp_time
        return

    def get_exposure_res(self):
        """Returns exposure resolution index: 0~ms, 1~us
        """
        index = self.cam.exp_res_index
        return index

    def set_exposure_res(self, index):
        """Sets the exposure resolution index.
        
        @param int index:  resolution index: 0~ms, 1~us
            You can check which exposure resolutions are supported by the camera via self.cam.exp_resolutions

        @return bool: True if set sucessfully, False if not
        """

        if index in [0,1] and type(index)==int:
            self.cam.exp_res = index
            return True
        else:
            return False

    def get_gain(self):
        """ Get the gain

        @return float: exposure gain
        """
        gain = self.cam.gain
        return gain

    def set_gain(self, gain):
        """ Set the gain

        CAMERA ONLY SUPPORTS GAIN OF 1. THIS FUNCTION WILL ONLY SET THE GAIN TO 1.

        @param float gain: desired new gain

        @return float: new exposure gain
        """
        if not(gain==1 and type(gain)==int):
            print(f'Prime95b only supports gain of 1. Setting gain to 1 insteaad of {gain}.')
            gain = int(1)
        self.cam.gain = gain
        new_gain = self.get_gain()
        return new_gain

    def get_ready_state(self):
        """ Is the camera ready for an acquisition ?

        @return bool: ready ?
        """
        if self.cam.is_open:
            return True
        else:
            return False

    def get_fan_speed(self):
        """Returns the fan speed of the camera.
        
        @return int: 0~'High', 1~'Medium', 2~'Low', 3~'Off'
        """
        fan_speed = self.cam.get_param(const.PARAM_FAN_SPEED_SETPOINT)
        return fan_speed

    def set_fan_speed(self, fan_speed):
        """Sets the fan speed of the camera.
        
        @param int fan_speed: 0~'High', 1~'Medium', 2~'Low', 3~'Off'

        @return int: fan speed setting
        """
        fs = {0: 'High', 1: 'Medium', 2: 'Low', 3: 'Off'}
        if fan_speed not in fs.keys():
            raise ValueError(f'Given fan speed {fan_speed} not recognized.')
        self.cam.set_param(const.PARAM_FAN_SPEED_SETPOINT, fan_speed)
        self.log.info(f'Prime95B fan speed: {fs[fan_speed]}')
        if fan_speed==3:
            self.log.warning('Ensure liquid cooling is on!')
        new_fan_speed = self.get_fan_speed
        return new_fan_speed

    def get_exposure_mode(self):
        """Returns the current exposure mode of the cammera.

        @return str: exp_mode
        """
        exp_mode = self.cam.exp_mode
        return exp_mode

    def set_exposure_mode(self, exp_mode):
        """Sets the exposure to exp_mode passed. Determines trigger behaviour. See constants.py for
        allowed values

        @param exp_mode str: string which is the key to the exposure mode dict in constants.py

        @return int: exposure mode as int
        """
        self.cam.exp_mode = exp_mode
        new_exp_mode = self.get_exposure_mode()
        return new_exp_mode