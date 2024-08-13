"""
Interface for coil magnet.

Question for the meeting:
    - What does decorator @abstractmethod do?
"""

from qudi.core.module import Base
from abc import abstractmethod

class CoilMagnetInterface(Base):
    """
    This interface is used to control a 3D coil magnet.
    """

    @abstractmethod
    def on_activate(self):
        """
        Properly activates the module.
        """
        pass


    @abstractmethod
    def  on_deactivate(self):
        """
        Properly deactivates the module.
        """
        pass


    @abstractmethod
    def ramp(self, field_target=[None,None,None], enter_persistent=False):
        """Ramps the magnet to the specified field target. Sends signal once done.
        
        @param array field_target: Target field in carthesian coordinates as array of length 3.

        @param bool enter_persistent: Specifies the state of the persistent switches (PSWs) after the ramp has finished.
            False: PSWs stay on, magnet stays in driven mode
            True: PSWs turn off, magnet enters persistent mode
        """
        pass


    @abstractmethod
    def ramp_to_zero(self):
        """
        Ramps the magnet to zero field.

        Returns signal once ramp is finished.
        """
        pass


    @abstractmethod
    def get_ramping_state(self):
        """
        Returns the ramping state of all three 1D magnets.

        @return list: list of ints with ramping status [status_x,status_y,status_z].
            integers mean the following:
                1:  RAMPING to target field/current
                2:  HOLDING at the target field/current
                3:  PAUSED
                4:  Ramping in MANUAL UP mode
                5:  Ramping in MANUAL DOWN mode
                6:  ZEROING CURRENT (in progress)
                7:  Quench detected
                8:  At ZERO current
                9:  Heating persistent switch
                10: Cooling persistent switch
        """
        pass


    @abstractmethod
    def pause_ramp(self):
        """Pauses the ramping process.
        
        The current/field will stay at the level it had when the function was executed.
        """
        pass


    @abstractmethod
    def continue_ramp(self):
        """
        Resumes ramping.
        """
        pass


    @abstractmethod     
    def abort_ramp(self):
        """
        Aborts the ramp.
        
        Aborts the ramp loops and pauses the ramp.
        """
        pass


    @abstractmethod
    def get_magnet_currents(self):
        """
        Reads the current that flows through the magnet coils.

        @return list: current in coil x, y and z as [curr_x,curr_y,curr_z]
        """
        pass


    @abstractmethod
    def get_supply_currents(self):
        """
        Reads the current that is applied by the power supply.

        @return list: current from supply x, y and z as [curr_x,curr_y,curr_z]
        """
        pass


    @abstractmethod
    def get_field(self):
        """
        Returns the magnetic field in x,y,z direction.

        @return list: magnetic field in x, y and z as [field_x,field_y,field_z]
        """
        pass
        

    @abstractmethod
    def check_field_amplitude(self,target_field):
        """
        Checks if the given field exceeds the constraints.
        
        @return int: Returns 0 if everything is okay, returns -1 if field is too strong.
        """
        pass


    @abstractmethod
    def combine_fields(self,field1,field2):
        """
        Combines the given fields.
        
        Combined field is max of individual fields.
        e.g. [1,2,3] and [2,2,2] would result in [2,2,3].

        @return list: x, y and z compinent of the combined field
        """
        pass

    
    @abstractmethod
    def equalize_currents(self):
        """
        Equalizes the current in the magnet and supply by ramping the supply current.
        """
        pass


    @abstractmethod
    def get_psw_status(self):
        """Returns the status of the psw heaters as array. 

        @return list: Status of the psw heaters as [status heater x, status heater y, status heater z]
            0 means heater is switched off.
            1 means heater is switched on.
        """
        pass


    @abstractmethod
    def set_psw_status(self, status):
        """
        Turns the PSWs of all 3 magnets on (1) or off (0). Before doing so it checks if the currents match.

        @param int status: desired status of the PSWS (0 off, 1 on)
        """
        pass
