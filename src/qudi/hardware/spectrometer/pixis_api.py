import numpy as np
from matplotlib import pyplot as plt
import ctypes
from ctypes import c_int64, c_int, c_double, c_void_p, byref, POINTER, Structure, c_longlong

FIXED_FRAME_SIZE = int(268000)
class PicamCameraID(ctypes.Structure):
    _fields_ = [
        ("model", c_int),
        ("computer_interface", c_int),
        ("sensor_name", ctypes.c_char * 64),
        ("serial_number", ctypes.c_char * 64),
    ]


class PicamAcquisitionErrorsMask(Structure):
    _fields_ = [("mask", c_int)]


class PicamReadout(ctypes.Structure):
    _fields_ = [
        
        ("frame_size", c_int),  # Size of the data frame
        ("data", POINTER(ctypes.c_int64)),  # Pointer to the readout data
    ]


class PicamAvailableData(Structure):
    _fields_ = [("initial_readout", c_void_p), ("readout_count", c_longlong)]


class SpectrometerController:
    def __init__(self, library_path):
        """
        Initialize the spectrometer controller.

        :param library_path: Path to the PICam shared library (DLL or .so file).
        """
        self.dll = ctypes.cdll.LoadLibrary(library_path)
        self.camera_handle = c_void_p()

    def check_error(self, error_code):
        """
        Check and raise an exception if the error code is not PicamError_None.

        :param error_code: Error code returned by a PICam function.
        """
        if error_code != 0:  # PicamError_None = 0
            raise Exception(f"PICam Error {error_code}: {self.get_error_string(error_code)}")

    def get_error_string(self, error_code):
        """
        Get a string description of the given error code.

        :param error_code: Error code returned by a PICam function.
        :return: Description of the error.
        """
        self.dll.Picam_GetEnumerationString.restype = ctypes.POINTER(ctypes.c_char_p)
        error_string = ctypes.c_char_p()
        self.dll.Picam_GetEnumerationString(c_int(1), error_code, byref(error_string))  # 1 = PicamEnumeratedType_Error
        return error_string.value.decode()

    def initialize(self):
        """Initialize the PICam library."""
        self.check_error(self.dll.Picam_InitializeLibrary())

    def uninitialize(self):
        """Uninitialize the PICam library."""
        self.check_error(self.dll.Picam_UninitializeLibrary())

    def open_camera(self, camera_id):
        """
        Open a specific camera by its ID.

        :param camera_id: An instance of PicamCameraID.
        """
        self.check_error(self.dll.Picam_OpenCamera(byref(camera_id), byref(self.camera_handle)))

    def close_camera(self):
        """Close the currently opened camera."""
        self.check_error(self.dll.Picam_CloseCamera(self.camera_handle))
        self.camera_handle = None


    def acquire_data(self, readout_count=3, timeout_ms=1000):
        """
        Acquire data from the spectrometer and ensure frame size matches the requirement.

        :param required_frame_size: Expected frame size for the acquisition.
        :param readout_count: Number of readouts to acquire.
        :param timeout_ms: Timeout in milliseconds for acquisition.
        :return: List of processed frames.
        """
        available_data = PicamAvailableData()
        errors = PicamAcquisitionErrorsMask()

        readouts = (PicamReadout * readout_count)()  # Array of structures
        for i in range(readout_count):
            # Pre-allocate memory for the frame data
            frame_buffer = (ctypes.c_int64 * FIXED_FRAME_SIZE)()
            readouts[i].data = frame_buffer
            readouts[i].frame_size = FIXED_FRAME_SIZE * ctypes.sizeof(ctypes.c_int64)  # Byte size


        available_data.initial_readout = ctypes.cast(readouts, c_void_p)

        self.check_error(
            self.dll.Picam_Acquire(
                self.camera_handle,
                c_int(readout_count),
                c_int(timeout_ms),
                byref(available_data),
                byref(errors),
            )
        )

        return self.process_available_data(available_data)
    
    def start_acquisition(self):
        """
        Start data acquisition.
        """
        self.check_error(self.dll.Picam_StartAcquisition(self.camera_handle))

    def stop_acquisition(self):
        """
        Stop data acquisition.
        """
        self.check_error(self.dll.Picam_StopAcquisition(self.camera_handle))

    def is_acquisition_running(self):
        """
        Check if acquisition is running.

        :return: True if acquisition is running, False otherwise.
        """
        running = c_int()
        self.check_error(self.dll.Picam_IsAcquisitionRunning(self.camera_handle, byref(running)))
        return bool(running.value)
    def list_cameras(self):
        """
        List available cameras.

        :return: List of PicamCameraID instances.
        """
        camera_ids = POINTER(PicamCameraID)()
        camera_count = c_int()
        self.check_error(self.dll.Picam_GetAvailableCameraIDs(byref(camera_ids), byref(camera_count)))

        cameras = []
        for i in range(camera_count.value):
            cameras.append(camera_ids[i])

        self.dll.Picam_DestroyCameraIDs(camera_ids)
        return cameras
        
    def process_available_data(self, available_data):
        """
        Process the available data from the acquisition.

        :param readouts: Array of PicamReadout structures.
        :param readout_count: Number of readouts to process.
        :return: List of processed frames.
        """
        dataArrayType = ctypes.c_uint16 * int(FIXED_FRAME_SIZE) #readoutstride
        dataArrayPointerType = ctypes.POINTER(dataArrayType)
        dataPointer = ctypes.cast(available_data.initial_readout, dataArrayPointerType)
        data = np.frombuffer(dataPointer.contents, dtype=np.uint16)
        d2d = np.array(data).reshape((int(200), int(1340)))

        return data, d2d

    def set_parameter(self, parameter_id, value):
        """
        Set a camera parameter.

        :param parameter: Parameter ID to set.
        :param value: Value to set for the parameter.
        """
        if isinstance(value, int):
            self.check_error(self.dll.Picam_SetParameterIntegerValue(self.camera_handle, parameter_id, c_int(value)))
        elif isinstance(value, float):
            self.check_error(self.dll.Picam_SetParameterFloatingPointValue(self.camera_handle, parameter_id, c_double(value)))
        else:
            raise TypeError("Unsupported parameter value type. Must be int or float.")

    def get_parameter(self, parameter_id):
        """
        parameter_id = inverted_parameters[60]  # For example, Exposure Time (0x02170017)
        Get the value of a camera parameter.

        :param parameter: Parameter ID to retrieve.
        :return: Value of the parameter.
        """
        value = c_double()
        self.check_error(self.dll.Picam_GetParameterFloatingPointValue(self.camera_handle, parameter_id, byref(value)))
        print(f"Value for Parameter {hex(parameter_id)}: {value}")
        return value.value

    def commit_params(self):
        failed_params = POINTER(ctypes.c_long)()
        failed_count = c_int()
        error_code = self.dll.Picam_CommitParameters(
            self.camera_handle,
            byref(failed_params),
            byref(failed_count),
        )
        self.check_error(error_code)
        # print(f"Parameters committed. Failed count: {failed_count.value}")


    def get_exposure_time(self):
        #exposure_time
        return  self.get_parameter(parameter_id=33685527)

    def set_exposure_time(self, value):
        #exposure_time
        self.set_parameter(parameter_id=33685527, 
                           value=float(value))
