import serial
import time
import re
class Acton300i:
    def __init__(self, port: str, baudrate: int = 9600, timeout: int = 2):
        """
        Initialize the connection to the Acton 300i spectrometer.
        
        Parameters:
            port (str): The COM port to connect to (e.g., 'COM3').
            baudrate (int): The baud rate for serial communication (default is 9600).
            timeout (int): The timeout for reading responses (in seconds).
        """
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout
        )
        


    def _send_command(self, command: str) -> str:
        """
        Send a command to the spectrometer and wait for the response.
        
        Parameters:
            command (str): The command to send.
        
        Returns:
            str: The response from the spectrometer.
        """
        self.ser.write((command + '\r').encode())  # Send the command with CR
        time.sleep(0.1)  # Allow processing time

        response = []
        while True:
            line = self.ser.readline().decode().strip()  # Read each line
            if not line:  # Stop reading when no more data
                break
            response.append(line)

        return '\n'.join(response)

    def wait_for_ok(self, timeout: int = 5):
        """
        Wait for an 'OK' response from the spectrometer with a timeout.
        
        Parameters:
            timeout (int): Maximum time to wait for the response (in seconds).
        
        Raises:
            TimeoutError: If the response is not received within the timeout.
        """
        start_time = time.time()
        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError("Timeout while waiting for 'OK' response from the spectrometer.")
            
            response = self.ser.readline().decode().strip()
            if response == "OK":
                break
            elif response:
                print(f"Unexpected response: {response}")

    def set_grating(self, grating_number: int, retries: int = 5, delay: float = 0.5):
        """
        Set the specified grating by its number and retry until 'ok' is received.
        
        Parameters:
            grating_number (int): The number of the grating to set (1-9).
            retries (int): Number of attempts to set the grating.
            delay (float): Delay between consecutive attempts (in seconds).
        
        Returns:
            str: Final response from the spectrometer.
        
        Raises:
            ValueError: If 'nok' is received or valid response not received after retries.
        """
        if not 1 <= grating_number <= 9:
            raise ValueError("Grating number must be between 1 and 9.")
        
        for attempt in range(retries):
            response = self._send_command(f"{grating_number} GRATING")
            if "ok" in response.lower():
                return response
            elif "nok" in response.lower():
                self.ser.close()  # Close the serial connection on 'nok'
                raise ValueError(f"Spectrometer returned 'nok' for grating {grating_number}.")
            
            time.sleep(delay)  # Wait before retrying

        raise ValueError(f"Failed to set grating {grating_number} after {retries} attempts.")

    def get_current_grating(self, retries: int = 5, delay: float = 0.5):
        """
        Get the currently selected grating with retries to ensure a valid response.
        
        Parameters:
            retries (int): Number of attempts to retrieve the current grating.
            delay (float): Delay between consecutive attempts (in seconds).
        
        Returns:
            int: Current grating number.
        
        Raises:
            ValueError: If a valid response is not received after retries or if 'nok' is encountered.
        """
        for attempt in range(retries):
            response = self._send_command("?GRATING")
            if "nok" in response.lower():
                self.ser.close()  # Close the serial connection on 'nok'
                raise ValueError("Spectrometer returned 'nok' when querying the current grating.")
            
            # Attempt to extract the grating number from the response
            match = re.search(r'\?GRATING\s(\d+)', response)
            if match:
                return int(match.group(1))  # Return the grating number as an integer
            
            time.sleep(delay)  # Wait before retrying
        
        raise ValueError("Failed to retrieve the current grating after multiple attempts.")


    def get_current_turret(self) -> str:
        """
        Get the currently selected turret.
        
        Returns:
            str: Current turret number.
        """
        return self._send_command("?TURRET")

    def set_turret(self, turret: int) -> str:
        """
        Set the specified turret by its number.
        
        Parameters:
            turret (int): The number of the turret to set (1-3).
        
        Returns:
            str: Response from the spectrometer.
        """
        if not 1 <= turret <= 3:
            raise ValueError("Turret number must be between 1 and 3.")
        return self._send_command(f"{turret} TURRET")

    def get_grating_info(self) -> str:
        """
        Get detailed information about all installed gratings.
        
        Returns:
            str: List of installed gratings with details.
        """
        return self._send_command("?GRATINGS")

    def set_wavelength(self, wavelength: float, retries: int = 5, delay: float = 0.5):
        """
        Set the monochromator to a specific wavelength and retry until 'ok' is received.
        
        Parameters:
            wavelength (float): The target wavelength in nanometers.
            retries (int): Number of attempts to set the wavelength.
            delay (float): Delay between consecutive attempts (in seconds).
        
        Returns:
            str: Final response from the spectrometer.
        
        Raises:
            ValueError: If 'nok' is received or valid response not received after retries.
        """
        if not 0 <= wavelength <= 1400:
            raise ValueError("Wavelength must be between 0 and 1400 nm.")
        
        for attempt in range(retries):
            response = self._send_command(f"{wavelength:.2f} GOTO")
            if "ok" in response.lower():
                return response
            elif "nok" in response.lower():
                self.ser.close()  # Close the serial connection on 'nok'
                raise ValueError(f"Spectrometer returned 'nok' for wavelength {wavelength:.2f} nm.")
            
            time.sleep(delay)  # Wait before retrying

        raise ValueError(f"Failed to set wavelength to {wavelength:.2f} nm after {retries} attempts.")


    def get_current_wavelength(self) -> str:
        """
        Get the current wavelength of the monochromator.
        
        Returns:
            str: Current wavelength in nanometers.
        """
        return self._send_command("?NM")

    def get_current_wavelength_value(self, retries: int = 5, delay: float = 0.5) -> float:
        """
        Query the current wavelength multiple times to ensure a valid response.
        
        Parameters:
            retries (int): Number of attempts to retrieve the wavelength.
            delay (float): Delay between consecutive attempts (in seconds).
        
        Returns:
            float: The wavelength value in nanometers.
        
        Raises:
            ValueError: If no valid wavelength is received after all attempts.
        """
        for attempt in range(retries):
            response = self._send_command("?NM")
            # Extract the wavelength using regex
            match = re.search(r'\?NM\s([\d.]+)\snm', response)
            if match:
                return float(match.group(1))
            
            time.sleep(delay)  # Wait before retrying
        
        raise ValueError("Failed to retrieve a valid wavelength after multiple attempts.")