from core.module import Base
from core.configoption import ConfigOption
from interface.servo_interface import servo_interface

import serial
import serial.tools.list_ports
import time

class ServoSerialInterface(Base, servo_interface):
    """ Hardware class to define the controls for the ESP32 servo controller.
    
    Example config for copy-paste:
    
    servo_control:
        module.Class: 'servo.servo_control.ServoSerialInterface'
        port: 'COM3'
        baudrate: 115200
        servo_limits:
            '1': [0, 360]    # ND-Filter servo
            '2': [0, 135]    # Laser-Tuning servo
    """

    _port = ConfigOption('port', 'COM3', missing='warn')
    _baud = ConfigOption('baudrate', 115200, missing='warn')
    _servo_limits = ConfigOption('servo_limits', {'1': (0, 180)}, missing='warn')

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.log.debug('The following configuration was found.')
        for key in config.keys():
            self.log.info('{0}: {1}'.format(key, config[key]))
        
        self.last_positions = {}
        self.available_servos = list(self._servo_limits.keys())
        self.ser = None
        self.is_startup = True  # Flag to track if we're in startup phase

    def on_activate(self):
        """ Activate the module """
        try:
            port = self.auto_detect_port() or self._port
            self.ser = serial.Serial(
                port=port,
                baudrate=self._baud,
                timeout=1,
                write_timeout=1
            )
            self.log.info(f"Servo interface activated on port {port}")
            # Set startup flag to True when activating
            self.is_startup = True
        except Exception as e:
            self.log.error(f"Failed to activate servo interface: {str(e)}")
            if self.ser is not None:
                try:
                    self.ser.close()
                except:
                    pass
                self.ser = None

    def auto_detect_port(self):
        """ Try to automatically detect the ESP32 port """
        try:
            for port in serial.tools.list_ports.comports():
                if 'USB' in port.description or 'ESP32' in port.description:
                    return port.device
            self.log.warning("ESP32 not found in available ports")
            return None
        except Exception as e:
            self.log.error(f"Error during port detection: {str(e)}")
            return None

    def request_position(self, servo_id):
        """ Request the last known position from the ESP32 using the 500 command """
        if not self.is_connected():
            self.log.error("Cannot request position - not connected")
            return None

        try:
            servo_id = str(servo_id)
            # Clear any pending data
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            
            # Send the 500 command to request position
            command = f"{servo_id}:VALUE\n"
            self.log.info(f"Servo: Requesting position with command: {command.strip()}")
            self.ser.write(command.encode())
            
            if self.is_startup:
                # During startup, use multiple attempts
                max_attempts = 10
                attempt = 0
                while attempt < max_attempts:
                    if self.ser.in_waiting:
                        response = self.ser.readline().decode().strip()
                        self.log.info(f"Servo: Received position response: {response}")
                        
                        if response and "101010" in response:
                            try:
                                position_str = response.split("Last positon: ")[1].strip()
                                position = float(position_str)
                               
                                self.last_positions[servo_id] = position
                                self.log.info(f"Servo: Retrieved position {position} for servo {servo_id}")
                                self.is_startup = False  # Clear startup flag after successful read
                                return position
                            except (ValueError, IndexError) as e:
                                self.log.error(f"Servo: Invalid position response format: {response}")
                                return None
                    
                    time.sleep(0.1)
                    attempt += 1
                
                self.log.warning(f"Servo: No valid position response received after {max_attempts} attempts")
                return None
            else:
                # After startup, just do a single read
                if self.ser.in_waiting:
                    response = self.ser.readline().decode().strip()
                    if response and "101010" in response:
                        try:
                            position_str = response.split("Last positon: ")[1].strip()
                            position = float(position_str)
                           
                            self.last_positions[servo_id] = position
                            return position
                        except (ValueError, IndexError) as e:
                            self.log.error(f"Servo: Invalid position response format: {response}")
                return None
                
        except Exception as e:
            self.log.error(f"Servo: Error requesting position: {str(e)}")
            return None

    def send_position(self, servo_id, position):
        """ Send a position command to a servo motor """
        if not self.is_connected():
            self.log.error("Cannot send position - not connected")
            return False

        try:
            servo_id = str(servo_id)
            min_pos, max_pos = self.get_position_limits(servo_id)
            if min_pos is not None and max_pos is not None:
                position = max(min_pos, min(position, max_pos))
            # else: do not clamp, allow any value

            # Clear any pending data
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

            # Format the command with float position
            command = f"{servo_id}:{position}\n"
            self.ser.write(command.encode())

            # Estimate wait time based on absolute angle difference and servo speed
            SERVO_SPEED_DEG_PER_SEC = 420.0  # max speed (70 rpm)
            MIN_RPM = 12.0  # minimum speed as set by setMinimalForce
            MIN_SPEED_DEG_PER_SEC = MIN_RPM * 6  # 1 RPM = 6 deg/sec
            MIN_WAIT = 0.5  # seconds, for very small moves
            MAX_WAIT = 15.0  # seconds, safety cap
            last_pos = self.last_positions.get(servo_id, 0)
            angle_diff = abs(float(position) - float(last_pos))
            # Time at max speed
            time_max = angle_diff / SERVO_SPEED_DEG_PER_SEC
            # Time at min speed
            time_min = angle_diff / MIN_SPEED_DEG_PER_SEC
            est_time = max(MIN_WAIT, min(max(time_max, time_min), MAX_WAIT)) + 0.5

            # Wait for response up to est_time
            import time
            start_time = time.time()
            response = ""
            while time.time() - start_time < est_time:
                if self.ser.in_waiting:
                    response = self.ser.readline().decode().strip()
                    break
                time.sleep(0.05)
            if response:
                try:
                    # Parse response in format "Sent to Servo X: Y.YY"
                    if f"Moved S{servo_id} to:" in response:
                        # Extract the position value after the colon
                        position_str = response.split(":")[1].strip()
                        new_position = float(position_str)
                        self.last_positions[servo_id] = new_position
                        return True
                    elif "Angle out of range" in response:
                        self.log.error(f"Servo: ESP32 rejected position: {response}")
                        return False
                    else:
                        # Try direct float conversion as fallback
                        new_position = float(response)
                        self.last_positions[servo_id] = new_position
                        return True
                except (ValueError, IndexError) as e:
                    self.log.error(f"Servo: Invalid response format: {response}")
                    return False
            else:
                self.log.error(f"Servo: No response received from servo after waiting {est_time:.2f} seconds for angle {angle_diff:.2f}")
                return False
        except Exception as e:
            self.log.error(f"Servo: Error sending position: {str(e)}")
            return False

    def on_deactivate(self):
        """ Deactivate the module """
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception as e:
                self.log.error(f"Error closing serial port: {str(e)}")
            self.ser = None

    def get_last_position(self, servo_id):
        """ Get the last known position of a servo motor """
        servo_id = str(servo_id)
        if self.is_startup:
            # Only request position from ESP32 during startup
            position = self.request_position(servo_id)
            if position is not None:
                return position
        # After startup, just return the cached position
        position = self.last_positions.get(servo_id)
        if position is None:
            position = self.request_position(servo_id)
        self.log.debug(f"Last known position for servo {servo_id}: {position}")
        return position

    def is_connected(self):
        """ Check if the serial connection is active """
        return self.ser is not None and self.ser.is_open

    def get_available_servos(self):
        """ Get a list of available servo IDs """
        return self.available_servos

    def get_position_limits(self, servo_id):
        """ Get the position limits for a servo """
        limits = self._servo_limits.get(str(servo_id), (None, None))
        if limits is None:
            return (None, None)
        return limits

    def process_serial_data(self):
        """ Process any incoming serial data """
        if not self.is_connected():
            return

        try:
            if self.ser.in_waiting:
                data = self.ser.readline().decode().strip()
                self.log.debug(f"Servo: Received data: {data}")

                # Handle position request response (101010)
                if data.startswith("101010"):
                    try:
                        parts = data.split(" Last positon: ")
                        if len(parts) == 2:
                            position = float(parts[1])
                            servo_id = str(self._get_servo_id_from_data(data))
                          
                            self.last_positions[servo_id] = position
                            self.log.info(f"Servo: Updated position from request: {position}")
                    except (ValueError, IndexError) as e:
                        self.log.error(f"Servo: Error parsing position request data: {str(e)}")

                # Handle incoming position updates (111000)
                elif data.startswith("111000"):
                    try:
                        parts = data.split(" Position: ")
                        if len(parts) == 2:
                            position = float(parts[1])
                            servo_id = str(self._get_servo_id_from_data(data))
                        
                            self.last_positions[servo_id] = position
                            self.log.info(f"Servo: Updated position from servo: {position}")
                    except (ValueError, IndexError) as e:
                        self.log.error(f"Servo: Error parsing position update data: {str(e)}")

        except Exception as e:
            self.log.error(f"Servo: Error processing serial data: {str(e)}")

    def _get_servo_id_from_data(self, data):
        """ Extract servo ID from the data string """
        try:
            # Look for "Slave X" pattern
            if "Slave" in data:
                parts = data.split("Slave")[1].split()
                if len(parts) > 0:
                    return int(parts[0])
        except Exception as e:
            self.log.error(f"Servo: Error extracting servo ID: {str(e)}")
        return None
