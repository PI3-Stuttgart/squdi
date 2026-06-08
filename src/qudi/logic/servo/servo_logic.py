from qudi.core.module import Base
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from abc import abstractmethod, ABC
from PySide2 import QtCore
import time


class servo_logic(ABC):
    """Abstract interface for servo logic (do NOT inherit Base here)."""

    @abstractmethod
    def move_servo_to(self, servo_id, position):
        """Move servo to specified position."""
        raise NotImplementedError

    @abstractmethod
    def change_servo_id(self, new_id):
        """Change active servo ID."""
        raise NotImplementedError

    @abstractmethod
    def get_position_limits(self, servo_id=None):
        """Get position limits for servo."""
        raise NotImplementedError

    @abstractmethod
    def get_available_servos(self):
        """Get list of available servos."""
        raise NotImplementedError

    @abstractmethod
    def get_last_position(self, servo_id=None):
        """Get last known position."""
        raise NotImplementedError


class ServoLogic(Base, servo_logic):
    servo_interface = Connector(interface='servo_interface')
    
    # Signal for GUI updates
    sigUpdate = QtCore.Signal()

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        self.servo_id = '1'
        self.servo_position = 0
        self.available_servos = []
        self.position_limits = {}
        self.data = {'time': [], '1': [], '2': []}

    def on_activate(self):
        self.servo = self.servo_interface()
        # Get available servos and their limits
        self.available_servos = self.servo.get_available_servos()
        if self.available_servos:
            self.servo_id = self.available_servos[0]
            self.position_limits = {
                servo_id: self.servo.get_position_limits(servo_id)
                for servo_id in self.available_servos
            }
        self.log.info(f"ServoLogic activated. Available servos: {self.available_servos}")

    def on_deactivate(self):
        """ Deactivate the module properly.
        
        This method ensures a clean shutdown by:
        1. Stopping any ongoing servo movements
        2. Disconnecting from the servo interface
        3. Clearing all data structures
        """
        self.log.info("Deactivating ServoLogic...")
        
        try:
            # Stop any ongoing movements
            if hasattr(self, 'servo') and self.servo is not None:
                if self.servo.is_connected():
                    self.log.info("Stopping servo movements...")
                    # Move to a safe position if needed
                    # self.move_servo_to(self.servo_id, 0)  # Uncomment if you want to move to home position
                    
                    # Disconnect from the servo interface
                    self.log.info("Disconnecting from servo interface...")
                    self.servo.on_deactivate()
            
            # Clear all data structures
            self.log.info("Clearing data structures...")
            self.data = {'time': [], '1': [], '2': []}
            self.available_servos = []
            self.position_limits = {}
            self.servo_position = 0
            
            self.log.info("ServoLogic deactivated successfully.")
            
        except Exception as e:
            self.log.error(f"Error during ServoLogic deactivation: {str(e)}")
            raise

    def move_servo_to(self, servo_id, position):
        """Send move command to hardware"""
        # Update the currently active servo ID in logic based on GUI selection
        self.servo_id = servo_id
       
        
        if not self.servo.is_connected():
            self.log.error("Cannot move servo - not connected")
            return False
            
        if self.servo_id not in self.available_servos:
            self.log.error(f"Invalid servo ID: {self.servo_id}")
            return False

        # Convert position to float
        try:
            position = float(position)
        except (ValueError, TypeError):
            self.log.error(f"Invalid position value: {position}")
            return False

        min_pos, max_pos = self.position_limits.get(self.servo_id, (None, None))
        if min_pos is not None and max_pos is not None:
            if not min_pos <= position <= max_pos:
                self.log.warning(f"Position {position} outside limits ({min_pos}, {max_pos})")
                position = max(min_pos, min(position, max_pos))
        # else: do not clamp, allow any value

        self.servo_position = position
        success = self.servo.send_position(self.servo_id, position)
        
        if success:
            # Verify the position was actually set
            actual_position = self.servo.get_last_position(self.servo_id)
            self.log.info(f"Logic: Servo {self.servo_id} reports actual position {actual_position}")
            
            # Update data for plotting
            current_time = time.time()
            self.data['time'].append(current_time)
            for servo_id in self.available_servos:
                pos = self.servo.get_last_position(servo_id)
                self.data[servo_id].append(pos if pos is not None else 0)
            # Keep only last 100 points
            if len(self.data['time']) > 100:
                self.data['time'] = self.data['time'][-100:]
                for servo_id in self.available_servos:
                    self.data[servo_id] = self.data[servo_id][-100:]
            self.sigUpdate.emit()
        else:
            self.log.error("Logic: Failed to send position command to hardware")
        return success

    def change_servo_id(self, new_id):
        """Change the active servo ID"""
        if new_id in self.available_servos:
            self.servo_id = new_id
            self.log.info(f"Logic: Changed to servo ID: {new_id}")
            self.sigUpdate.emit() # Emit update signal after changing servo ID
            return True
        self.log.error(f"Logic: Invalid servo ID: {new_id}")
        return False

    def get_position_limits(self, servo_id=None):
        """Get position limits for a servo"""
        if servo_id is None:
            servo_id = self.servo_id
        return self.position_limits.get(servo_id, (0, 180))

    def get_available_servos(self):
        """Get list of available servo IDs"""
        return self.available_servos

    def get_last_position(self, servo_id=None):
        """Get the last known position of current or specified servo"""
        if servo_id is None:
            servo_id = self.servo_id
        return self.servo.get_last_position(servo_id)
