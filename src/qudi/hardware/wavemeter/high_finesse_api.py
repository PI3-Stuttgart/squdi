import ctypes
from threading import Thread, Lock, Event
import time
import numpy as np
import os # Added for path operations

buffer_size = 20

# --- Define constants from the WLM manual (refer to chapter 4.1.8 and others) ---
# Operation Mode Constants (page 124 of the manual PDF)
cStop = ctypes.c_uint16(0x0000)
cCtrlStartMeasurement = ctypes.c_uint16(0x0002) # For starting measurement without recording [cite: 1628]
cCtrlStartRecord = ctypes.c_uint16(0x0004)    # For starting measurement *with* recording [cite: 1628]
# Additional Operation Flag Constants (page 125 of the manual PDF)
cCtrlOverwrite = ctypes.c_uint16(0x1000)     # To overwrite an existing file during recording [cite: 1629]
cCtrlFileASCII = ctypes.c_uint16(0x4000) # For saving as ASCII

class WLM():
    
    class BufferThread(Thread):
        query_interval = 0.25 
        def __init__(self, wlm ,*args, **kwargs):
            super(WLM.BufferThread, self).__init__(*args, **kwargs) # Corrected super call
            self.wlm = wlm
            self.mutex = Lock()
            self.tt = time.time()
            self.dt = 0
            self.wavelengths = []
            self._stop_event = Event()

        def stop(self):
            self._stop_event.set()

        def stopped(self):
            return self._stop_event.isSet()

        def empty_buffer(self):
            self.mutex.acquire()
            self.wavelengths = []
            self.mutex.release()

        def run(self):
            self._wavelengths = []
            while True:
                if self.stopped():
                    return
                
                wavelength = self.wlm.get_wavelength(channel=1) 
                if not np.isnan(wavelength): 
                    self._wavelengths.append(wavelength)
                
                if len(self._wavelengths) >= buffer_size: 
                    self.mutex.acquire()
                    self.wavelengths = self._wavelengths[:] 
                    self.mutex.release()
                    self._wavelengths = []

                    # Use walrus operator (Python 3.8+)
                    current_time = time.time()
                    dt_calc = current_time - self.tt
                    if dt_calc > 0: 
                        self.dt = dt_calc
                    self.tt = current_time
                
                time.sleep(self.query_interval)

    def __init__(self):
        try:
            self.dll = ctypes.windll.LoadLibrary('wlmData.dll')
        except OSError as e:
            print(f"Fatal Error: Could not load wlmData.dll. Ensure it's in the system PATH. Details: {e}")
            raise
            
        self.reference_course_center = None
        self.wavelengths_main_class = [] # Renamed to avoid confusion with BufferThread.wavelengths
        self.reference_course_amplitude = None
        
        # Setup common function prototypes
        try:
            self.dll.Operation.restype = ctypes.c_long
            self.dll.Operation.argtypes = [ctypes.c_uint16]

            self.dll.SetOperationFile.restype = ctypes.c_long
            self.dll.SetOperationFile.argtypes = [ctypes.c_char_p]
            
            self.dll.GetWavelengthNum.restype = ctypes.c_double
            self.dll.GetWavelengthNum.argtypes = [ctypes.c_long, ctypes.c_double]

            self.dll.ConvertUnit.restype = ctypes.c_double
            self.dll.ConvertUnit.argtypes = [ctypes.c_double, ctypes.c_long, ctypes.c_long]

            self.dll.GetPIDCourseNum.restype = ctypes.c_long
            # argtypes for GetPIDCourseNum (ctypes.c_char_p) set in method

            self.dll.SetPIDCourseNum.restype = ctypes.c_long
            # argtypes for SetPIDCourseNum (ctypes.c_char_p) set in method
            
            self.dll.GetDeviationMode.restype = ctypes.c_bool
            self.dll.GetDeviationMode.argtypes = [ctypes.c_bool] 
            
            self.dll.SetDeviationMode.restype = ctypes.c_long
            self.dll.SetDeviationMode.argtypes = [ctypes.c_bool]

            self.dll.GetDeviationSensitivity.argtypes = [ctypes.c_long]
            self.dll.GetDeviationSensitivity.restype = ctypes.c_long

            self.dll.SetDeviationSensitivity.argtypes = [ctypes.c_long]
            self.dll.SetDeviationSensitivity.restype = ctypes.c_long

            self.dll.GetDeviationSignalNum.argtypes = [ctypes.c_long, ctypes.c_double]
            self.dll.GetDeviationSignalNum.restype = ctypes.c_double

            self.dll.SetDeviationSignalNum.argtypes = [ctypes.c_long, ctypes.c_double]
            self.dll.SetDeviationSignalNum.restype = ctypes.c_long

        except AttributeError as e:
            print(f"Error setting up DLL function prototypes: {e}")
            raise 

        # self.buffer_thread = self.BufferThread(self)
        # self.start_buffer()

    def start_measurements(self):
        """Starts the Wavelength Meter in standard measurement mode (not recording to file)."""
        print("Starting WLM measurements (not recording)...")
        result = self.dll.Operation(cCtrlStartMeasurement) # Uses cCtrlStartMeasurement [cite: 1628]
        if result != 0: # ResERR_NoErr is 0
            print(f"Warning: start_measurements call failed with DLL code {result}.")
        return result
    
    def stop_measurements(self):
        """Stops any active WLM operation (measurement, recording, etc.)."""
        print("Stopping WLM operations...")
        result = self.dll.Operation(cStop) # Uses cStop [cite: 1628]
        if result != 0:
            print(f"Warning: stop_measurements call failed with DLL code {result}.")
        return result
    
    # --- New methods for file recording ---
    def set_recording_file(self, output_directory: str, filename: str):
        # long SetOperationFile(char *Filename) [cite: 1046]
        # This function tells the software the name of the file to use[cite: 1045].
        set_operation_file_func = self.dll.SetOperationFile
        set_operation_file_func.restype = ctypes.c_long
        # Use ctypes.c_char_p for string pointers (char*).
        set_operation_file_func.argtypes = [ctypes.c_char_p]
        if not os.path.exists(output_directory):
            os.makedirs(output_directory)
            print(f"Created directory: {output_directory}")

        filename = os.path.join(output_directory, f"{filename}.ltr").encode('utf-8')
        result = set_operation_file_func(filename)
        print(f"Data will be recorded to: {filename}")
        return result
        

# Inside your WLM class:

    def start_recording(self, save_as_ascii: bool = True, overwrite: bool = False):
        """
        Starts recording measurements to the file previously set by set_recording_file().
        Corresponds to Operation(cCtrlStartRecord) in the DLL.
        Args:
            save_as_ascii: If True, saves the recording as an ASCII (.ltx) file.
                        Otherwise, saves as binary (.ltr).
            overwrite: If True, an existing file will be overwritten.
        Returns:
            Integer DLL return code (0 for success, ResERR_NoErr).
        """
        current_command_val = cCtrlStartRecord.value
        log_message = "Starting binary (.ltr) recording..."

        if save_as_ascii:
            current_command_val |= cCtrlFileASCII.value # Combine with ASCII flag
            log_message = "Starting ASCII (.ltx) recording..."
            print("Note: Consider using a '.ltx' file extension when setting the filename for ASCII recordings.")

        if overwrite:
            current_command_val |= cCtrlOverwrite.value
            log_message += " (overwrite enabled)..."
        else:
            log_message += "..."

        print(log_message)
        # The Operation function expects a c_uint16 for the command
        result = self.dll.Operation(ctypes.c_uint16(current_command_val))

        if result != 0: # ResERR_NoErr is 0
            print(f"Warning: start_recording call failed with DLL code {result}.")
        else:
            print("Recording started successfully.")
        return result
    def stop_recording(self):
        """
        Stops the current recording (and any other measurement activity).
        Corresponds to Operation(cStop) in the DLL. [cite: 1037, 1628]
        Returns:
            Integer DLL return code (0 for success, ResERR_NoErr).
        """
        print("Stopping recording...")
        result = self.dll.Operation(cStop) # cStop stops all operations including recording
        if result != 0:
            print(f"Warning: stop_recording call failed with DLL code {result}.")
        else:
            print("Recording stopped successfully.")
        return result
    # --- End of new methods ---

    def get_wavelength(self, channel: int = 1, units: str ='THz') -> float:
        if not isinstance(channel, int):
            raise TypeError("Channel must be an integer.")
        if not isinstance(units, str):
            raise TypeError("Units must be a string.")

        try:
            wavelength_vac = self.dll.GetWavelengthNum(ctypes.c_long(channel), ctypes.c_double(0))
            
            # Handle error codes or no value (see manual page 67, 126)
            if wavelength_vac == 0.0: # ErrNoValue is 0
                return float('nan') 
            if wavelength_vac < 0: # Negative values are error codes
                # print(f"Debug: GetWavelengthNum for channel {channel} returned error code: {wavelength_vac}")
                return float('nan')
            
            # If units is 'vac' (vacuum nm) or 'nm' (assuming vacuum nm by convention)
            requested_units_lower = units.lower()
            if requested_units_lower == 'vac' or requested_units_lower == 'nm':
                return wavelength_vac
            else:
                return self.convert_wavelength(wavelength_vac, 'vac', requested_units_lower)
        except Exception as e:
            print(f"Critical error in get_wavelength for channel {channel}, units '{units}': {e}")
            return float('nan')

    def empty_buffer(self):
        if hasattr(self, 'buffer_thread') and self.buffer_thread.is_alive():
            self.buffer_thread.empty_buffer()
        else:
            print("Buffer thread not running or not initialized. Cannot empty buffer.")

    def get_wavelength_buffer(self): # Removed unused 'channel' and 'units' args
        if not hasattr(self, 'buffer_thread') or not self.buffer_thread.is_alive():
            print("Buffer thread not running or not initialized. Cannot get buffer.")
            return [], 0
            
        self.buffer_thread.mutex.acquire()
        buffer_copy = self.buffer_thread.wavelengths[:] 
        dt_copy = self.buffer_thread.dt
        # Clearing the source buffer after copy
        self.buffer_thread.wavelengths = [] 
        self.buffer_thread.mutex.release()
        
        return buffer_copy, dt_copy
            
    def get_reference_course(self, channel: int = 1) -> str:
        if not isinstance(channel, int):
            raise TypeError("Channel must be an integer.")
        string_buffer = ctypes.create_string_buffer(1024)
        self.dll.GetPIDCourseNum.argtypes = [ctypes.c_long, ctypes.c_char_p] # Pointer type
        
        result = self.dll.GetPIDCourseNum(ctypes.c_long(channel), string_buffer)
        if result != 0: # ResERR_NoErr is 0
            print(f"Warning: GetPIDCourseNum for channel {channel} failed with DLL code {result}.")
            return ""
        return string_buffer.value.decode('utf-8', errors='ignore')

    def set_reference_course(self, function_str: str, channel: int = 1):
        if not isinstance(function_str, str):
            raise TypeError("Reference course function_str must be a string.")
        if not isinstance(channel, int):
            raise TypeError("Channel must be an integer.")

        try:
            function_str_stripped = function_str.strip()
            if not function_str_stripped:
                raise ValueError("Function string cannot be empty.")

            if '+' in function_str_stripped and '*' in function_str_stripped:
                if function_str_stripped.index('+') < function_str_stripped.index('*'):
                    center_wavelength_str,  scan_params_str = function_str_stripped.split('+', 1)
                    scan_amplitude_str, _ = scan_params_str.split('*', 1) # scan_function_str not used here
                    self.reference_course_center = float(center_wavelength_str.strip())
                    self.reference_course_amplitude = float(scan_amplitude_str.strip())
                else:
                    raise ValueError("Center wavelength should appear before scan parameters. Expected format: 'c_lambda + amplitude * func(...)'")
            else: 
                self.reference_course_center = float(function_str_stripped)
                self.reference_course_amplitude = None
            
            # Basic validation for center wavelength
            if self.reference_course_center <= 0: # Wavelengths are typically positive
                raise ValueError("Reference course center wavelength must be a positive value.")
        except ValueError as e:
            print(f"Error parsing reference course string '{function_str}': {e}")
            return -1 # Example error return

        self.dll.SetPIDCourseNum.argtypes = [ctypes.c_long, ctypes.c_char_p] # Pointer type
        encoded_function = function_str_stripped.encode('utf-8')
        # Create a buffer of the exact size needed + null terminator if string_buffer used that way
        # Or pass directly if c_char_p handles it. Create_string_buffer is safer.
        string_param = ctypes.c_char_p(encoded_function)
        
        result = self.dll.SetPIDCourseNum(ctypes.c_long(channel), string_param)
        if result != 0:
            print(f"Warning: SetPIDCourseNum for channel {channel}, function '{function_str_stripped}' failed with DLL code {result}.")
        return result
        
    def convert_wavelength(self, wavelength: float, from_units: str, to_units: str) -> float:
        # Unit mapping based on manual constants (page 125)
        # cReturnWavelengthVac = 0, cReturnWavelengthAir = 1, cReturnFrequency = 2
        # cReturnWavenumber = 3, cReturnPhotonEnergy = 4
        unit_map = {
            'vac': 0, 'nm': 0, # 'nm' often implies vacuum nanometers
            'air': 1,
            'thz': 2,
            '1/cm': 3, 'cm-1': 3, 'wavenumber': 3,
            'ev': 4, 'photonenergy': 4
        }
        
        from_val = unit_map.get(from_units.lower())
        to_val = unit_map.get(to_units.lower())

        if from_val is None:
            raise ValueError(f"Invalid 'from_units' for conversion: '{from_units}'. Supported: {list(unit_map.keys())}")
        if to_val is None:
            raise ValueError(f"Invalid 'to_units' for conversion: '{to_units}'. Supported: {list(unit_map.keys())}")
        
        converted_val = self.dll.ConvertUnit(ctypes.c_double(wavelength), 
                                           ctypes.c_long(from_val), 
                                           ctypes.c_long(to_val))
        # Handle ConvertUnit error codes (page 111, 126 in PDF for ErrDiv0, ErrUnitNotAvailable)
        if int(converted_val) == -13: # ErrDiv0
            print(f"Warning: ConvertUnit returned ErrDiv0 (division by zero) for wavelength {wavelength}.")
            return float('nan')
        # ErrUnitNotAvailable (-15) is less likely due to map, but good to be aware
        
        return converted_val

    def get_regulation_mode(self) -> bool:
        # The argument to GetDeviationMode is reserved and a dummy value should be passed.
        return self.dll.GetDeviationMode(ctypes.c_bool(False)) 
    
    def set_regulation_mode(self, mode: bool = False):
        if not isinstance(mode, bool):
            raise TypeError("Regulation mode must be a boolean (True or False).")
        result = self.dll.SetDeviationMode(ctypes.c_bool(mode))
        if result != 0:
            print(f"Warning: SetDeviationMode for mode '{mode}' failed with DLL code {result}.")
        return result

    def get_deviation_sensitivity(self) -> int:
        # Argument is reserved, pass 0.
        return self.dll.GetDeviationSensitivity(ctypes.c_long(0))

    def set_deviation_sensitivity(self, sensitivity: int):
        if not isinstance(sensitivity, int):
            raise TypeError("Sensitivity must be an integer.")
        result = self.dll.SetDeviationSensitivity(ctypes.c_long(sensitivity))
        if result != 0:
            print(f"Warning: SetDeviationSensitivity for value '{sensitivity}' failed with DLL code {result}.")
        return result
    
    def get_deviation_signal(self, channel: int = 1) -> float:
        if not isinstance(channel, int):
            raise TypeError("Channel must be an integer.")
        # Second argument to GetDeviationSignalNum is reserved.
        return self.dll.GetDeviationSignalNum(ctypes.c_long(channel), ctypes.c_double(0))

    def set_deviation_signal(self, deviation: float, channel: int = 1):
        if not isinstance(deviation, (float, int)):
            raise TypeError("Deviation signal must be a number (float or int).")
        if not isinstance(channel, int):
            raise TypeError("Channel must be an integer.")
            
        result = self.dll.SetDeviationSignalNum(ctypes.c_long(channel), ctypes.c_double(float(deviation)))
        if result != 0:
            print(f"Warning: SetDeviationSignalNum for channel {channel}, deviation '{deviation}' failed with DLL code {result}.")
        return result

    def start_trigger(self, signal_channel=1, trigger_channel=4):
        print(f"Placeholder: start_trigger called with signal_channel={signal_channel}, trigger_channel={trigger_channel}. Not yet fully implemented.")
        pass
    
    def stop_trigger(self):
        print("Placeholder: stop_trigger called. Not yet fully implemented.")
        pass
    
    def start_buffer(self): 
        if hasattr(self, 'buffer_thread') and self.buffer_thread.is_alive():
            print("Buffer thread is already running.")
            return

        self.buffer_thread = self.BufferThread(self) 
        try:
            self.buffer_thread.start()
            print("Buffer thread started.")
        except RuntimeError as e:
            print(f"Error starting buffer thread (it might have been started and stopped before): {e}")
            # If thread can only be started once, re-instantiate
            self.buffer_thread = self.BufferThread(self)
            self.buffer_thread.start()
            print("Re-initialized and started buffer thread.")


    def stop_buffer(self):
        if hasattr(self, 'buffer_thread') and self.buffer_thread.is_alive():
            self.buffer_thread.stop()
            self.buffer_thread.join() # Wait for the thread to finish
            print("Buffer thread stopped and joined.")
            # Python threads cannot be restarted. A new instance must be created if needed.
            # Deliberately not creating a new instance here; let start_buffer handle it.
        else:
            print("Buffer thread not running or not initialized. Nothing to stop.")