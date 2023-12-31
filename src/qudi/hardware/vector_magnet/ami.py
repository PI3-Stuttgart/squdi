from cmath import isclose
import numpy as np
import socket
from time import sleep

from qudi.core.module import Base
from qudi.core.configoption import ConfigOption

class AMI430(Base):
    _ip = ConfigOption(name='ip', missing='warn')
    _port = ConfigOption(name='port', missing='warn')

    def __init__(self, ip=None, port=None,**kwargs):
        if ip:
            self._ip = ip
        if port:
            self._port = port
        super().__init__(**kwargs)


    def on_activate(self):
        self.connect()
        self.remote()
        self.set_params_from_config()
        return


    def on_deactivate(self):
        self.local()
        self.disconnect()
        return


    def connect(self, ip=None, port=None):
        if not ip:
            ip = self._ip
        if not port:
            port = self._port
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.connect((ip, port))
            greeting = self._read()
            print(greeting)
            if not "American Magnetics Model 430 IP Interface" in greeting:
                raise RuntimeError(f"Device does not answer with correct greeting message.\nRecieved message:\n{greeting}")
        except Exception as err:
            self.disconnect()
            raise


    def disconnect(self):
        try:
            self._socket.close()
        except Exception as err:
            raise


    def _read(self, length=1024):
        """Reads the feedback from the device."""
        return self._socket.recv(length).decode("ascii").strip().split("\r\n")


    def _write(self, cmd):
        """Writes the specified command to the decive without waiting for a response."""
        return self._socket.send( (cmd+"\r\n").encode("ascii"))


    def _query(self, cmd):
        """Writes the specified command to the device and waits for a response. 
        
        Will take forever, if no response is given. In this case use _write."""
        self._write(cmd)
        return self._read()


    def local(self):
        """Enables the front panel.
        
        Local acess is now possible. """
        self._write('SYST:LOC')


    def remote(self):
        """Disables the front control panel to prevent accidental operation."""
        self._write('SYST:REM')


    def idn(self):
        """ Returns the identification string of the Model 430 Programmer.
        
        The identification string contains the AMI model number and firmware revision code.
        """
        return self._query("*IDN?")


    def read_error(self):
        """Reads out the error buffer.
        
        From manual:
        Up to 10 errors are stored in the error buffer.
        Errors are retrieved in first-in-first-out (FIFO) order.
        The error buffer is cleared by the *CLS (clear status) command or when the power is cycled.
        Errors are also cleared as they are read.
        
        """
        self._query('SYST:ERR?')

    
    def reset(self):
        """ Resets the Model 430 Programmer.
        
        From manual:
        This is equivalent to cycling the power to the Model 430 Programmer using the power switch. 
        All non-volatile calibration data and battery-backed memory is restored. 
        Status is cleared according to the *PSC setting.
        
        FOr explanation of individual erroes see manual  section 4.6 (page 153).
        """

        self._write('RST')


    def get_coil_constant(self):
        """Returns the coil constant setting in kG/A or T/A per the selected field units."""
        ans = self._query('COIL?')
        ans=float(ans[0])
        return ans


    def get_field_units(self):
        """Returns the unit for the field.
        "0" means kilogauss, "1" means tesla.
        """
        ans = self._query('FIELD:UNITS?')
        ans=int(ans[0])
        return ans
    

    def set_field_units(self, unit='1'):
        """Sets the unit for the field.
        
        '0', 'kG' or 'kGs' sets it to kilogauss (default).

        '1' or 'T' sets it to tesla.
        """
        unit = str(unit)
        alias_seconds = ['0', 'kG', 'kGs']
        alias_minutes = ['1', 'T']
        if unit in alias_seconds:
            # set field unit to kilogauss
            self._write('CONF:FIELD:UNITS 0')
        elif unit in alias_minutes:
            # set field unit to tesla
            self._write('CONF:FIELD:UNITS 1')
        else:
            raise Exception('Unknown unit entered.')


    def get_ramp_rate_units(self):
        """Returns the unit for the ramp rate.
        "0" means 1/s, "1" means 1/min.
        """
        ans = self._query('RAMP:RATE:UNITS?')
        ans=int(ans[0])
        return ans
    

    def set_ramp_rate_units(self, unit='min'):
        """Sets the unit for the ramp rate.
        
        '0', 's' or 'sek' sets it to seconds (default).

        '1' or 'min' sets it to minutes.
        """
        unit = str(unit)
        alias_seconds = ['0', 's', 'sek']
        alias_minutes = ['1', 'min']
        if unit in alias_seconds:
            # set ramp rate in terms of seconds
            self._write('CONF:RAMP:RATE:UNITS 0')
        elif unit in alias_minutes:
            # set ramp rate in terms of minutes
            self._write('CONF:RAMP:RATE:UNITS 1')
        else:
            raise Exception('Unknown unit entered.')


    def get_number_of_segments(self):
        n_segments = self._query('RAMP:RATE:SEGMENTS?')
        n_segments = int(n_segments[0])
        return n_segments


    def set_number_of_segments(self,n_segments):
        """Sets the number of ramp rate segments.
        """
        write = f'CONFIGURE:RAMP:RATE:SEGEMNTS {n_segments}'
        self._write(write)
        return 0


    def get_ramp_rates(self):
        """ Returns the ramp rates in specified units and upper bound in amp.

        @return list ramp_rates: list of lists. Each list consists of the ramp rate for the segment
            and the upper bound of the segment. Units are the specified ones (kG, T, s, min).
        """
        n_segments = self.get_number_of_segments()
        ramp_rates = []
        for i in range(1,n_segments+1):
            query = f'RAMP:RATE:FIELD:{i}?'
            ramp_rate = self._query(query)
            ramp_rates.append(ramp_rate)
        return ramp_rates


    def set_ramp_rate(self, segment_number, rate, upper_bound):
        """Sets the ramp rate for the specified segement.
        
        @param int segment_number: Number of the target segment. Firs segment has number 1.

        @param float rate: Ramp rate in specified units (kG,T per s,min).

        @param float upper_bound: upper bound for the segemnt in kG or T.
        """
        write = f'CONF:RAMP:RATE:FIELD {segment_number},{rate},{upper_bound}'
        self._write(write)
        return 0

    def get_target_field(self):
        """Returns the target field in kilogauss or tesla, depending on the selected field units.
        
        A coil constant needs to be defined for this command. 
        This is because field gets calculated from current via coil constant.
        """
        ans = self._query('FIELD:TARG?')
        ans=float(ans[0])
        return ans


    def get_field(self):
        """Returns the calculated field in kG or T (depending on selected field units).
        
        This query requires that a coil constant be defined; otherwise, an error is generated.
        The field is calculated by multiplying the measured magnet current by the coil constant.
        If the magnet is in persistent mode, the command returns the field that was present when persistent mode was entered.
        """
        ans = self._query('FIELD:MAG?')
        ans=float(ans[0])
        return ans

    
    def ramp_to_zero(self):
        """Places the Model 430 Programmer in ZEROING CURRENT mode:
        
        Ramping automatically initiates and continues at the ramp rate until the power supply output current is less than 0.1% of Imax,
        at which point the AT ZERO status becomes active.
        """
        self._write('ZERO')


    def get_psw_installed(self):
        """Checks if a persistent switch is installed on the connected superconducting magnet.
        
        Returns 1 if one is connected, 0 if not.
        """
        ans = self._query('PSWITCH:INSTALLED?')
        ans = int(ans[0])
        return ans


    def get_psw_cool_time(self):
        """Returns the cooling time that was set for the persistent swich.

        After this time has passed, the persistent switch should be superconducting.
        """
        ans = self._query('PSWITCH:COOLTIME?')
        ans = int(ans[0])
        return ans


    def get_psw_heat_time(self):
        """Returns the heating time that was set for the persistent swich.
        """
        ans = self._query('PSWITCH:HEATTIME?')
        ans = int(ans[0])
        return ans

    
    def set_psw_status(self, status):
        """Turns the psw on (1) or off(0).

        System needs to be in the HOLDING state.
        Current on power supply needs to match current inside magnet.
        Then PSW can be heated.
        """

        # check if device is in HOLDING mode (ramp has finished).
        state = self.get_ramping_state()
        if not (state == 2 or state == 8):
            raise Exception('Device needs to be in HOLDING or ZERO mode.\nRamping state is {state}')

        # check if curent inside and outside match.
        curr_mag = self.get_magnet_current()
        curr_sup = self.get_supply_current()
        if not np.isclose(curr_mag, curr_sup,atol=0.01): #tolerance needs to be quite high due to noise
            raise Exception('Current on powern supply does not match current inside magnet ' + str(self) + '.')

        if type(status) == int:
            if status == 0 or status == 1:
                self._write('PSWITCH ' + str(status))
            else:
                raise Exception('Status needs to be either 0 or 1.')
        else:
            raise TypeError('Status needs to be integer.')
        return


    def get_persistent(self):
        """ Returns mode of the magnet.

        0 if in driven mode,
        1 if in persistent mode.

        Note: If current in magnet is less than 100 mA, AMI will not say that one is in persistent mode, eventhough PSW is cold.
        """
        ans = self._query('PERSISTENT?')
        ans = int(ans[0])
        return ans



    def get_pseudo_persistent(self):
        """Returns mode of the magnet.

        0 if in driven mode,
        1 if in persistent mode.

        Note: If current in magnet is less than 100 mA, AMI will not say that magnet is in persistent mode, eventhough PSW is cold.
        This function fixes that issue.
        If the heatä
        So if the above requirements are met (magnet in HOLDING or ZERO, PSW heater off, current less than 100 mA), this function will return 1.
        """

        # magnet mode (persistent or driven)
        mode = self.get_persistent()
        # current in magnet
        curr_mag = self.get_magnet_current()
        # ramping state
        state = self.get_ramping_state()
        # heater status
        heater = self.get_psw_status()

        if mode == 1:
            pseudo_mode = 1
        else:
            if heater==0 and curr_mag <= 0.1:
                if state==(2 or 8): # HOLD, ZERO
                    pseudo_mode = 1
                else:
                    pseudo_mode = 0
            else:
                pseudo_mode = 0
        return pseudo_mode


    def ramp(self, field_target=None, current_target=None):
        """ Starts ramping towards the voltage/current limit.

        The ramp needs to be set up beforehand (ramp rate, limits ,etc.).
        Usually you only want to specify the field but in certain circumstances
        (e.g. adapting current inside magnet and from power supply) you would like to specify the current.
        TODO: Not sure if this is the case, I think we can always work in field.
        You can only choose a voltage ramp or a current ramp.
        """
        
        #make sure that only one parameter is specified
        if field_target==None and not current_target==None:
            self.set_target_current(current_target)
        elif current_target==None and not field_target==None:
            self.set_target_field(field_target)
        else:
            raise RuntimeError('You need to give either field or current target.')
        
        self.continue_ramp()


    def get_constraints(self): 
        pass

# ------------------------------------------------------------------------------------------------
# stuff that is used in the functions above
    


    def set_params_from_config(self):
        pass


    def set_target_field(self,target,unit=None):
        """Sets the target field in kilogauss or tesla, depending on the selected field units.
        
        A coil constant needs to be defined for this command.

        @param target: target field

        @param unit: unit for the field. See set_field_units() for details. Skip if units should not be changed.
        """
        if not unit == None:
            self.set_field_units(unit)
        self._write('CONF:FIELD:TARG ' + str(target))


    def set_target_current(self, target):
        """Sets the target current in amperes."""
        self._write('CONF:CURR:TARG ' + str(target))


    def get_magnet_current(self):
        """Returns the current flowing in the magnet.
        
        Returns the current flowing in the magnet in amperes, 
        expressed as a number with four significant digits past the decimal point, such as 5.2320. 
        If the magnet is in persistent mode, the command returns the current that was flowing in the magnet when persistent mode was entered.
        """
        ans = self._query('CURR:MAG?')
        ans=float(ans[0])
        return ans
    

    def get_supply_current(self):
        """Returns the measured power supply current in amperes."""
        ans = self._query('CURR:SUPP?')
        ans=float(ans[0])
        return ans


    def continue_ramp(self):
        """Resumes ramping.
        
        Puts the power supply in automatic ramping mode. Ramping resumes until target field/current is reached.
        """
        self._write('RAMP')


    def pause_ramp(self):
        """Pauses the ramping process.
        
        The current/field will stay at the level it has now.
        """
        self._write('PAUSE')


    def get_ramping_state(self):
        """Returns the integer value of the current ramping state.

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
        ans = self._query('STATE?')
        ans=int(ans[0])
        return ans


    def get_psw_status(self):
        """Returns the status of the psw heater. 
        
        0 means heater is switched off.
        1 means heateris switched on.
        """
        ans = self._query('PSWITCH?')
        ans = int(ans[0])
        return ans


    def equalize_currents(self):
        """Ramps the supply current to the value of the magnet current."""
        curr_mag = self.get_magnet_current()
        curr_sup = self.get_supply_current()
        if np.isclose(curr_mag, curr_sup,atol=0.01):
            return 0
        else:
            self.ramp(current_target=curr_mag)
            while True: # run until currents are the same (should only take a couple of seconds if ramp speed is set correctly)
                sleep(2) # TODO: find something that does not freezue qudi
                if np.isclose(curr_mag, curr_sup,atol=0.01):
                    return 0



    def set_target_field(self,target,unit=None):
        """Sets the target field in kilogauss or tesla, depending on the selected field units.
        
        A coil constant needs to be defined for this command.

        @param target: target field

        @param unit: unit for the field. See set_field_units() for details. Skip if units should not be changed.
        """
        if not unit == None:
            self.set_field_units(unit)
        self._write('CONF:FIELD:TARG ' + str(target))