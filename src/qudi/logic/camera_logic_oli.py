from qtpy import QtCore
import time

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from collections import OrderedDict

class Cameralogic(LogicBase):
    """Controls a camera.
    """
    # connectors
    camera = Connector(name='camera', interface='CameraInterface')

    # config options
    exposure_time = ConfigOption(name='exposure_time',default=0.1)

    ## signals
    # to hardware
    sigChangeExposureTime = QtCore.Signal(float)
    sigChangeCameraGain = QtCore.Signal(float)
    sigAcquireImage = QtCore.Signal()
    # to gui
    sigUpdateDisplay = QtCore.Signal()

    

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)

    def on_activate(self):
        # connectors
        self._camera = self.camera()

        # connect signals
        # to hardware
        self.sigChangeExposureTime.connect(self._camera.set_exposure)
        self.sigChangeCameraGain.connect(self._camera.set_gain)
        self.sigAcquireImage.connect(self._camera.emit_acquired_data)
        # from hardware
        self._camera.sigAcquisitionDone.connect(self._acquire_image_done)

        # set values from config
        self.set_exposure_time(self.exposure_time)

        self._last_image = None
        self._continuous_acquisition = True # if set to True, new picture will be taken right after old one has finished.

        return

    def on_deactivate(self):
        pass

    def set_exposure_time(self,exposure_time):
        """Tells the camera to change the exposure time (in seconds).
        """
        self.sigChangeExposureTime.emit(exposure_time)
        return

    def set_camera_gain(self,gain):
        """Tells the camera to change the gain.
        """
        self.sigChangeCameraGain.emit(gain)
        return

    def return_image(self):
        """Takes an image and returns it. Also updated _last_image.
        
        It waits for the camera to take and return an image. This freezes the program.
        If you don't want this to happen, use acquire_single_image() and catch then catch the 
            signal that is emitted by the hardware.

        @ return ndarray: 2d array of the image.
        """
        img = self._camera.get_acquired_data()
        self._last_image = img
        return img

    def _acquire_image(self):
        """ Tells the camera to take a picture.
        
        Result will be caught by function below.
        """
        self.sigAcquireImage.emit()
        pass

    def acquire_single_image(self):
        self._continuous_acquisition = False
        self._acquire_image()
        return

    def _acquire_image_done(self,img_matrix):
        """Handles the signal after an image was acquired.
        """
        self._last_image = img_matrix
        self.sigUpdateDisplay.emit()
        if self._continuous_acquisition:
            self._acquire_image()
        return

    def get_last_image(self):
        """Returns the last image that the camera acquired.
        """
        return self._last_image

    def start_continuous_acquisition(self):
        """Starts continuous acquisition.
        """
        self._continuous_acquisition = True
        self._acquire_image()
        return

    def stop_continuous_acquisition(self):
        """Stops continuous acquisition.
        """
        self._continuous_acquisition = False
        return

    def record_movie(self,n_frames,int_time_frame):
        """Records n_frames frames with int_time_frame seconds integration time per frame.

        Total time of movie is longer than n_frames*int_time_frame
            because of unobserved time between frames.

        PROBLEM: The generated dict has some issues.
            Calling img_dict.keys() in a different file/the command prompt results in a Type Error:
            TypeError: descriptor '__len__' of 'dict_keys' object needs an argument
        SOME INVESTIGATION:
            The dictionary is a dict inside this function <class 'dict'>
            Once returned, it turns into something diffrent <netref class 'rpyc.core.netref.type'>
        WORKAROUND:
            Turn into dict in new file:  img_dict = dict(img_dict)
        

        @ param int n_frames: number of frames

        @ param float int_time_frame: integration time for each frame in seconds

        @ return dict: dictionary of the images. Key is timestamp, content is 2d-array with picture
        """
        # get old exposure time
        old_int_time = self._camera.get_exposure()
        self.set_exposure_time(int_time_frame)
        img_dict = dict()
        starting_time = time.time()
        for i in range(n_frames):
            img = self.return_image()
            timestamp = time.time() - starting_time
            img_dict[timestamp] = img
        # set exposure time back to previous value
        self.set_exposure_time(old_int_time)
        print(type(img_dict))

        return img_dict