import ctypes
from ctypes import c_int, c_double, c_void_p, byref, POINTER, create_string_buffer
import numpy as np


class PICam:
    """Wrapper for the PICam API for managing Princeton Instruments cameras."""

    def __init__(self, dll_path: str = "pvcam64.dll"):
        """Initialize the PICam API and load the DLL."""
        self.dll = ctypes.windll.LoadLibrary(dll_path)
        self.camera_handle = c_void_p()
        self.check_error(self.dll.Picam_InitializeLibrary())
        print("PICam Library Initialized")

    def __del__(self):
        """Ensure the library is uninitialized on destruction."""
        self.uninitialize_library()

    def check_error(self, error_code: int):
        """Check the return code from PICam functions and raise an error if needed."""
        if error_code != 0:  # 0 indicates PicamError_None
            error_message = f"PICam Error Code: {error_code}"
            raise RuntimeError(error_message)

    def uninitialize_library(self):
        """Uninitialize the PICam library."""
        self.check_error(self.dll.Picam_UninitializeLibrary())
        print("PICam Library Uninitialized")

    def open_first_camera(self):
        """Open the first available camera."""
        self.check_error(self.dll.Picam_OpenFirstCamera(byref(self.camera_handle)))
        print("Camera Opened")

    def close_camera(self):
        """Close the currently opened camera."""
        if self.camera_handle:
            self.check_error(self.dll.Picam_CloseCamera(self.camera_handle))
            self.camera_handle = None
            print("Camera Closed")

    def get_camera_id(self):
        """Retrieve the camera ID."""
        camera_id = create_string_buffer(64)
        self.check_error(self.dll.Picam_GetCameraID(self.camera_handle, byref(camera_id)))
        return camera_id.value.decode()

    def set_exposure_time(self, exposure_time: float):
        """Set the exposure time for the camera."""
        param = 0x17000017  # PicamParameter_ExposureTime (from picam.h)
        self.check_error(self.dll.Picam_SetParameterFloatingPointValue(self.camera_handle, param, c_double(exposure_time)))
        print(f"Exposure Time Set: {exposure_time} ms")

    def start_acquisition(self):
        """Start data acquisition."""
        self.check_error(self.dll.Picam_StartAcquisition(self.camera_handle))
        print("Acquisition Started")

    def stop_acquisition(self):
        """Stop data acquisition."""
        self.check_error(self.dll.Picam_StopAcquisition(self.camera_handle))
        print("Acquisition Stopped")

    def acquire_frame(self, readout_count: int, timeout_ms: int = 5000):
        """Acquire a frame from the camera."""
        available_data = PicamAvailableData()
        errors = c_int()
        self.check_error(
            self.dll.Picam_Acquire(
                self.camera_handle,
                c_int(readout_count),
                c_int(timeout_ms),
                byref(available_data),
                byref(errors),
            )
        )
        if errors.value != 0:
            raise RuntimeError(f"Acquisition Errors: {errors.value}")

        # Convert the data into a NumPy array
        frame = np.ctypeslib.as_array(
            ctypes.cast(available_data.initial_readout, POINTER(c_double)),
            shape=(readout_count,),
        )
        return frame


class PicamAvailableData(ctypes.Structure):
    """Structure representing available data from a PICam acquisition."""
    _fields_ = [
        ("initial_readout", ctypes.c_void_p),
        ("readout_count", ctypes.c_int64),
    ]


if __name__ == "__main__":
    # Example Usage
    try:
        camera = PICam("pvcam64.dll")
        camera.open_first_camera()
        print("Camera ID:", camera.get_camera_id())
        camera.set_exposure_time(10.0)  # Set exposure time to 10 ms
        camera.start_acquisition()

        # Acquire a single frame
        frame = camera.acquire_frame(readout_count=1)
        print("Acquired Frame:", frame)

        camera.stop_acquisition()
        camera.close_camera()
    except Exception as e:
        print("Error:", e)
    finally:
        del camera
